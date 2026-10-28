"""
Rota Segura PE - aplicativo desktop (Tkinter)

Funcionalidades:
  - Mapa interativo (OpenStreetMap) com sua posição, delegacia mais próxima e rota pelas ruas (OSRM)
  - Posição por IP, ou manual (clique direito no mapa > "Definir minha posição aqui")
  - Botão "ENVIAR LOCALIZAÇÃO EM TEMPO REAL": compartilha sua localização ao vivo (Telegram Live Location)
    com o contato/grupo configurado em config.json, junto com os dados da delegacia mais próxima.
  - Botão para abrir o WhatsApp com a mensagem pronta (link do mapa + delegacia)

Dependências:  pip install tkintermapview requests
Gerar .exe:    pip install pyinstaller
               pyinstaller --onefile --noconsole --collect-all tkintermapview --name RotaSegurePE rota_segura.py
"""
import json
import math
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import quote

import requests
import tkintermapview

# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DELEGACIAS_PATH = BASE_DIR / "data" / "delegacias_pe.json"

CONFIG_PADRAO = {
    "telegram_bot_token": "",      # token do bot criado no @BotFather
    "telegram_chat_id": "",        # id do seu contato/grupo de confiança que receberá a localização
    "whatsapp_numero": "",         # opcional, formato internacional sem +, ex: 5581999999999
    "intervalo_segundos": 10,      # frequência de atualização da localização ao vivo
    "origem_padrao": [-8.0560, -34.8980],
}

DELEGACIAS_PADRAO = [
    {"nome": "01ª Delegacia de Santo Amaro", "tipo": "Polícia Civil",
     "endereco": "Rua da Aurora, 487 - Santo Amaro, Recife - PE",
     "latitude": -8.0582, "longitude": -34.8815, "telefone": "(81) 3184-3450", "atendimento_24h": True},
    {"nome": "1ª Delegacia da Mulher (DEAM Recife)", "tipo": "Delegacia da Mulher",
     "endereco": "Praça do Campo Santo, s/n - Santo Amaro, Recife - PE",
     "latitude": -8.0512, "longitude": -34.8885, "telefone": "(81) 3184-3352", "atendimento_24h": True},
    {"nome": "02ª Delegacia do Espinheiro", "tipo": "Polícia Civil",
     "endereco": "Rua da Hora, 853 - Espinheiro, Recife - PE",
     "latitude": -8.0435, "longitude": -34.8962, "telefone": "(81) 3184-3470", "atendimento_24h": True},
    {"nome": "07ª Delegacia de Boa Viagem", "tipo": "Polícia Civil",
     "endereco": "Av. Domingos Ferreira, 4420 - Boa Viagem, Recife - PE",
     "latitude": -8.1258, "longitude": -34.9025, "telefone": "(81) 3184-3530", "atendimento_24h": True},
    {"nome": "09ª Delegacia do Varadouro (Olinda)", "tipo": "Polícia Civil",
     "endereco": "Av. Sigismundo Gonçalves, 305 - Varadouro, Olinda - PE",
     "latitude": -7.9995, "longitude": -34.8510, "telefone": "(81) 3184-3580", "atendimento_24h": True},
]

ZONAS_RISCO = [
    {"nome": "Trecho Crítico / Baixa Iluminação", "latitude": -8.0535, "longitude": -34.8910, "raio": 180}
]


def carregar_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(CONFIG_PADRAO, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    return {**CONFIG_PADRAO, **cfg}


def carregar_delegacias():
    if DELEGACIAS_PATH.exists():
        with open(DELEGACIAS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return DELEGACIAS_PADRAO


# ==============================================================================
# GEO
# ==============================================================================
def distancia_haversine(c1, c2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, (c1[0], c1[1], c2[0], c2[1]))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def delegacia_mais_proxima(origem, delegacias):
    melhor = min(delegacias, key=lambda d: distancia_haversine(origem, (d["latitude"], d["longitude"])))
    return {**melhor, "distancia_metros": distancia_haversine(origem, (melhor["latitude"], melhor["longitude"]))}


def obter_rota(origem, destino):
    url = f"https://router.project-osrm.org/route/v1/driving/{origem[1]},{origem[0]};{destino[1]},{destino[0]}"
    try:
        r = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=10)
        if r.status_code == 200 and r.json().get("routes"):
            rota = r.json()["routes"][0]
            return {
                "coords": [(p[1], p[0]) for p in rota["geometry"]["coordinates"]],
                "dist": rota["distance"],
                "dur": rota["duration"],
            }
    except Exception:
        pass
    d = distancia_haversine(origem, destino)
    return {"coords": [tuple(origem), tuple(destino)], "dist": d, "dur": d / 8.5}


def localizacao_por_ip():
    """Localização aproximada pelo IP (desktop não tem GPS). Retorna (lat, lon) ou None."""
    try:
        r = requests.get("http://ip-api.com/json/?fields=status,lat,lon", timeout=8).json()
        if r.get("status") == "success":
            return (r["lat"], r["lon"])
    except Exception:
        pass
    return None


def circulo(lat, lon, raio_m, n=40):
    pts = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        dlat = (raio_m * math.cos(ang)) / 111320
        dlon = (raio_m * math.sin(ang)) / (111320 * math.cos(math.radians(lat)))
        pts.append((lat + dlat, lon + dlon))
    return pts


# ==============================================================================
# ENVIO DE LOCALIZAÇÃO (Telegram Live Location)
# ==============================================================================
class TelegramLive:
    def __init__(self, token, chat_id):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.message_id = None

    def _post(self, metodo, **dados):
        r = requests.post(f"{self.base}/{metodo}", data={"chat_id": self.chat_id, **dados}, timeout=15)
        j = r.json()
        if not j.get("ok"):
            raise RuntimeError(j.get("description", "erro desconhecido do Telegram"))
        return j["result"]

    def iniciar(self, pos, texto):
        self._post("sendMessage", text=texto)
        res = self._post("sendLocation", latitude=pos[0], longitude=pos[1], live_period=86400)
        self.message_id = res["message_id"]

    def atualizar(self, pos):
        if self.message_id:
            self._post("editMessageLiveLocation", message_id=self.message_id,
                       latitude=pos[0], longitude=pos[1])

    def parar(self):
        if self.message_id:
            try:
                self._post("stopMessageLiveLocation", message_id=self.message_id)
                self._post("sendMessage", text="Compartilhamento de localização encerrado.")
            except Exception:
                pass
            self.message_id = None


def link_mapa(pos):
    return f"https://www.google.com/maps?q={pos[0]:.6f},{pos[1]:.6f}"


# ==============================================================================
# INTERFACE
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rota Segura PE")
        self.geometry("1100x700")
        self.cfg = carregar_config()
        self.delegacias = carregar_delegacias()
        self.pos = tuple(self.cfg["origem_padrao"])
        self.delegacia = None
        self.compartilhando = False
        self.telegram = None
        self.marker_user = self.marker_del = self.path = None

        self._montar_ui()
        self._desenhar_zonas()
        self.atualizar_posicao(self.pos)
        self.after(200, self.buscar_por_ip)

    # ---------- UI ----------
    def _montar_ui(self):
        painel = ttk.Frame(self, padding=10, width=320)
        painel.pack(side="left", fill="y")
        painel.pack_propagate(False)

        ttk.Label(painel, text="Rota Segura PE", font=("Arial", 16, "bold")).pack(anchor="w")
        self.lbl_pos = ttk.Label(painel, text="", wraplength=290)
        self.lbl_pos.pack(anchor="w", pady=(8, 2))
        self.lbl_del = ttk.Label(painel, text="", wraplength=290, justify="left")
        self.lbl_del.pack(anchor="w", pady=4)
        self.lbl_rota = ttk.Label(painel, text="", wraplength=290, font=("Arial", 10, "bold"))
        self.lbl_rota.pack(anchor="w", pady=4)

        ttk.Button(painel, text="Atualizar posição (IP)", command=self.buscar_por_ip).pack(fill="x", pady=2)
        ttk.Label(painel, text="Dica: clique direito no mapa para definir\nsua posição manualmente.",
                  foreground="#555").pack(anchor="w", pady=(0, 10))

        self.btn_enviar = tk.Button(
            painel, text="🚨 ENVIAR LOCALIZAÇÃO\nEM TEMPO REAL", bg="#D32F2F", fg="white",
            font=("Arial", 12, "bold"), height=3, command=self.alternar_envio)
        self.btn_enviar.pack(fill="x", pady=6)

        tk.Button(painel, text="Enviar por WhatsApp", bg="#25D366", fg="white",
                  font=("Arial", 10, "bold"), command=self.enviar_whatsapp).pack(fill="x", pady=2)

        self.lbl_status = ttk.Label(painel, text="Compartilhamento: desligado", wraplength=290)
        self.lbl_status.pack(anchor="w", pady=8)

        ttk.Separator(painel).pack(fill="x", pady=8)
        ttk.Label(painel, text="EMERGÊNCIA (ligue pelo celular)", font=("Arial", 9, "bold")).pack(anchor="w")
        ttk.Label(painel, text="190 Polícia Militar\n180 Central da Mulher\n197 Polícia Civil (disque-denúncia)").pack(anchor="w")

        self.mapa = tkintermapview.TkinterMapView(self, corner_radius=0)
        self.mapa.pack(side="right", fill="both", expand=True)
        # OSM bloqueia o app (403) e o CARTO passou a exigir API key.
        # Esri World Street Map não exige chave. Atribuição: © Esri, HERE, Garmin, OpenStreetMap contributors
        self.mapa.set_tile_server(
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
            max_zoom=19)
        self.mapa.set_zoom(14)
        self.mapa.add_right_click_menu_command("Definir minha posição aqui", self.definir_manual, pass_coords=True)

    def _desenhar_zonas(self):
        for z in ZONAS_RISCO:
            self.mapa.set_polygon(circulo(z["latitude"], z["longitude"], z["raio"]),
                                  fill_color="#D32F2F", outline_color="#D32F2F",
                                  border_width=2, name=z["nome"])

    # ---------- posição / rota ----------
    def definir_manual(self, coords):
        self.atualizar_posicao((coords[0], coords[1]))

    def buscar_por_ip(self):
        self.lbl_status.config(text="Buscando posição por IP...")
        def tarefa():
            p = localizacao_por_ip()
            self.after(0, lambda: self._pos_ip(p))
        threading.Thread(target=tarefa, daemon=True).start()

    def _pos_ip(self, p):
        if p:
            self.atualizar_posicao(p)
            self.lbl_status.config(text="Posição por IP é aproximada. Ajuste com clique direito no mapa se precisar.")
        else:
            self.lbl_status.config(text="Não foi possível obter posição por IP.")

    def atualizar_posicao(self, pos):
        self.pos = tuple(pos)
        self.delegacia = delegacia_mais_proxima(self.pos, self.delegacias)
        destino = (self.delegacia["latitude"], self.delegacia["longitude"])

        self.lbl_pos.config(text=f"Sua posição: {self.pos[0]:.5f}, {self.pos[1]:.5f}")
        self.lbl_del.config(text=(f"Delegacia mais próxima:\n{self.delegacia['nome']}\n"
                                  f"{self.delegacia['endereco']}\nTel: {self.delegacia['telefone']}"))
        self.lbl_rota.config(text="Calculando rota...")

        if self.marker_user:
            self.marker_user.delete()
        if self.marker_del:
            self.marker_del.delete()
        self.marker_user = self.mapa.set_marker(self.pos[0], self.pos[1], text="Você", marker_color_circle="#2E7D32",
                                                marker_color_outside="#43A047")
        self.marker_del = self.mapa.set_marker(destino[0], destino[1], text=self.delegacia["nome"],
                                               marker_color_circle="#0D47A1", marker_color_outside="#1976D2")
        self.mapa.set_position(*self.pos)

        def tarefa(pos=self.pos):
            rota = obter_rota(pos, destino)
            self.after(0, lambda: self._mostrar_rota(rota, pos))
        threading.Thread(target=tarefa, daemon=True).start()

    def _mostrar_rota(self, rota, pos_calculada):
        if pos_calculada != self.pos:  # posição mudou enquanto calculava
            return
        if self.path:
            self.path.delete()
        self.path = self.mapa.set_path(rota["coords"], color="#00897B", width=6)
        self.lbl_rota.config(text=f"Rota: {rota['dist'] / 1000:.2f} km  |  ~{int(rota['dur'] / 60)} min")

    # ---------- envio ----------
    def _texto_alerta(self):
        d = self.delegacia
        return ("🚨 ALERTA - Preciso de ajuda.\n"
                f"Minha localização: {link_mapa(self.pos)}\n"
                f"Delegacia mais próxima: {d['nome']}\n{d['endereco']}\nTel: {d['telefone']}")

    def alternar_envio(self):
        if self.compartilhando:
            self.parar_envio()
        else:
            self.iniciar_envio()

    def iniciar_envio(self):
        token, chat = self.cfg["telegram_bot_token"], self.cfg["telegram_chat_id"]
        if not token or not chat:
            messagebox.showwarning(
                "Configuração necessária",
                f"Preencha telegram_bot_token e telegram_chat_id em:\n{CONFIG_PATH}\n\n"
                "Ou use o botão 'Enviar por WhatsApp'.\n\n"
                "Em perigo imediato, ligue 190.")
            return
        self.telegram = TelegramLive(token, chat)
        self.lbl_status.config(text="Iniciando compartilhamento...")

        def tarefa():
            try:
                self.telegram.iniciar(self.pos, self._texto_alerta())
                self.after(0, self._envio_iniciado)
            except Exception as e:
                self.after(0, lambda: self._erro_envio(str(e)))
        threading.Thread(target=tarefa, daemon=True).start()

    def _envio_iniciado(self):
        self.compartilhando = True
        self.btn_enviar.config(text="⏹ PARAR COMPARTILHAMENTO", bg="#424242")
        self.lbl_status.config(text="Compartilhando localização ao vivo...")
        self._ciclo_atualizacao()

    def _erro_envio(self, msg):
        self.lbl_status.config(text=f"Falha ao enviar: {msg}")

    def _ciclo_atualizacao(self):
        if not self.compartilhando:
            return
        pos = self.pos

        def tarefa():
            try:
                self.telegram.atualizar(pos)
                self.after(0, lambda: self.lbl_status.config(
                    text=f"Compartilhando ao vivo ✔ ({pos[0]:.5f}, {pos[1]:.5f})"))
            except Exception as e:
                msg = str(e)
                if "not modified" not in msg:  # posição igual à anterior não é erro
                    self.after(0, lambda: self.lbl_status.config(text=f"Erro na atualização: {msg}"))
        threading.Thread(target=tarefa, daemon=True).start()
        self.after(int(self.cfg["intervalo_segundos"]) * 1000, self._ciclo_atualizacao)

    def parar_envio(self):
        self.compartilhando = False
        if self.telegram:
            threading.Thread(target=self.telegram.parar, daemon=True).start()
        self.btn_enviar.config(text="🚨 ENVIAR LOCALIZAÇÃO\nEM TEMPO REAL", bg="#D32F2F")
        self.lbl_status.config(text="Compartilhamento: desligado")

    def enviar_whatsapp(self):
        numero = self.cfg.get("whatsapp_numero", "")
        base = f"https://wa.me/{numero}" if numero else "https://wa.me/"
        webbrowser.open(f"{base}?text={quote(self._texto_alerta())}")

    def destroy(self):
        if self.compartilhando:
            self.parar_envio()
        super().destroy()


if __name__ == "__main__":
    App().mainloop()

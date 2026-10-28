"""
Botão "Mostrar delegacia mais próxima": marca a delegacia no mapa, traça a rota pelas ruas (OSRM)
e exibe endereço, telefone e distância.

Dependências:  pip install tkintermapview requests
Gerar .exe:    python -m pip install pyinstaller
               python -m PyInstaller --onefile --noconsole --collect-all tkintermapview --name RotaSegurePE main.py
"""
import json
import math
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import requests
import tkintermapview

# ==============================================================================
# DADOS
# ==============================================================================
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DELEGACIAS_PATH = BASE_DIR / "data" / "delegacias_pe.json"

POSICAO_PADRAO = (-8.0560, -34.8980)  # usada se não conseguir localizar por IP

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
                "aproximada": False,
            }
    except Exception:
        pass
    d = distancia_haversine(origem, destino)
    return {"coords": [tuple(origem), tuple(destino)], "dist": d, "dur": d / 8.5, "aproximada": True}


def localizacao_por_ip():
    """Localização aproximada pelo IP. Retorna (lat, lon) ou None."""
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
# INTERFACE
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rota Segura PE")
        self.geometry("1100x700")
        self.delegacias = carregar_delegacias()
        self.pos = POSICAO_PADRAO
        self.marker_user = self.marker_del = self.path = None
        self.versao_rota = 0  # evita que uma rota antiga apareça depois de mudar a posição

        self._montar_ui()
        self._desenhar_zonas()
        self.definir_posicao(self.pos)
        self.after(200, self.buscar_por_ip)

    def _montar_ui(self):
        painel = ttk.Frame(self, padding=10, width=320)
        painel.pack(side="left", fill="y")
        painel.pack_propagate(False)

        ttk.Label(painel, text="Rota Segura PE", font=("Arial", 16, "bold")).pack(anchor="w")
        self.lbl_pos = ttk.Label(painel, text="", wraplength=290)
        self.lbl_pos.pack(anchor="w", pady=(8, 2))
        self.lbl_status = ttk.Label(painel, text="", wraplength=290, foreground="#555")
        self.lbl_status.pack(anchor="w", pady=2)

        ttk.Button(painel, text="Atualizar posição (IP)", command=self.buscar_por_ip).pack(fill="x", pady=(8, 2))
        ttk.Label(painel, text="Dica: clique direito no mapa para definir\nsua posição manualmente.",
                  foreground="#555").pack(anchor="w", pady=(0, 10))

        tk.Button(painel, text="📍 MOSTRAR DELEGACIA\nMAIS PRÓXIMA", bg="#1976D2", fg="white",
                  font=("Arial", 12, "bold"), height=3, command=self.mostrar_delegacia).pack(fill="x", pady=6)

        self.lbl_info = ttk.Label(painel, text="", wraplength=290, justify="left")
        self.lbl_info.pack(anchor="w", pady=8)
        self.lbl_rota = ttk.Label(painel, text="", wraplength=290, font=("Arial", 10, "bold"))
        self.lbl_rota.pack(anchor="w")

        ttk.Separator(painel).pack(fill="x", pady=10)
        ttk.Label(painel, text="EMERGÊNCIA (ligue pelo celular)", font=("Arial", 9, "bold")).pack(anchor="w")
        ttk.Label(painel, text="190 Polícia Militar\n180 Central da Mulher\n197 Polícia Civil (disque-denúncia)").pack(anchor="w")

        self.mapa = tkintermapview.TkinterMapView(self, corner_radius=0)
        self.mapa.pack(side="right", fill="both", expand=True)
        # OSM bloqueia o app (403) e o CARTO exige API key. Esri não exige chave.
        # Atribuição: © Esri, HERE, Garmin, OpenStreetMap contributors
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

    # ---------- posição ----------
    def definir_manual(self, coords):
        self.definir_posicao((coords[0], coords[1]))

    def buscar_por_ip(self):
        self.lbl_status.config(text="Buscando posição por IP...")

        def tarefa():
            p = localizacao_por_ip()
            self.after(0, lambda: self._pos_ip(p))
        threading.Thread(target=tarefa, daemon=True).start()

    def _pos_ip(self, p):
        if p:
            self.definir_posicao(p)
            self.lbl_status.config(text="Posição por IP é aproximada. Ajuste com clique direito no mapa se precisar.")
        else:
            self.lbl_status.config(text="Não foi possível obter posição por IP. Use o clique direito no mapa.")

    def definir_posicao(self, pos):
        self.pos = tuple(pos)
        self.lbl_pos.config(text=f"Sua posição: {self.pos[0]:.5f}, {self.pos[1]:.5f}")
        self._limpar_delegacia()
        if self.marker_user:
            self.marker_user.delete()
        self.marker_user = self.mapa.set_marker(self.pos[0], self.pos[1], text="Você",
                                                marker_color_circle="#2E7D32", marker_color_outside="#43A047")
        self.mapa.set_position(*self.pos)

    def _limpar_delegacia(self):
        self.versao_rota += 1
        for item in (self.marker_del, self.path):
            if item:
                item.delete()
        self.marker_del = self.path = None
        self.lbl_info.config(text="")
        self.lbl_rota.config(text="")

    # ---------- delegacia mais próxima ----------
    def mostrar_delegacia(self):
        self._limpar_delegacia()
        pos = self.pos
        d = delegacia_mais_proxima(pos, self.delegacias)
        destino = (d["latitude"], d["longitude"])
        plantao = "24 horas" if d.get("atendimento_24h") else "Horário comercial"

        self.marker_del = self.mapa.set_marker(destino[0], destino[1], text=d["nome"],
                                               marker_color_circle="#0D47A1", marker_color_outside="#1976D2")
        self.lbl_info.config(text=(f"{d['nome']}\n{d.get('tipo', '')}\n{d['endereco']}\n"
                                   f"Tel: {d['telefone']}\nPlantão: {plantao}\n"
                                   f"Em linha reta: {d['distancia_metros'] / 1000:.2f} km"))
        self.lbl_rota.config(text="Calculando rota...")

        # enquadra usuário + delegacia na tela
        self.mapa.fit_bounding_box((max(pos[0], destino[0]), min(pos[1], destino[1])),
                                   (min(pos[0], destino[0]), max(pos[1], destino[1])))

        versao = self.versao_rota

        def tarefa():
            rota = obter_rota(pos, destino)
            self.after(0, lambda: self._mostrar_rota(rota, versao))
        threading.Thread(target=tarefa, daemon=True).start()

    def _mostrar_rota(self, rota, versao):
        if versao != self.versao_rota:
            return
        self.path = self.mapa.set_path(rota["coords"], color="#00897B", width=6)
        if rota["aproximada"]:
            self.lbl_rota.config(text="Rota pelas ruas indisponível. Mostrando linha reta.")
        else:
            self.lbl_rota.config(text=f"Rota: {rota['dist'] / 1000:.2f} km  |  ~{int(rota['dur'] / 60)} min de carro")


if __name__ == "__main__":
    App().mainloop()

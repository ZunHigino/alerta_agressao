import math
import webbrowser
from pathlib import Path
import requests
import folium
from folium.plugins import LocateControl


# ==============================================================================
# 1. CONFIGURAÇÕES E PONTO DE PARTIDA (PERNAMBUCO)
# ==============================================================================
# Coordenadas do usuário / ponto de partida (Ex: Derby, Recife - PE)
# Pode alterar para qualquer coordenada em Pernambuco:
PONTO_ORIGEM = [-8.0560, -34.8980]  # [Latitude, Longitude]


# ==============================================================================
# 2. BASE DE DELEGACIAS E ZONAS DE RISCO
# ==============================================================================
# Carrega do arquivo do projeto se existir
def carregar_delegacias():
    caminho_json = Path("data/delegacias_pe.json")
    if caminho_json.exists():
        import json
        with open(caminho_json, "r", encoding="utf-8") as f:
            return json.load(f)

    # Base essencial de delegacias de Pernambuco
    return [
        {
            "nome": "01ª Delegacia de Santo Amaro",
            "tipo": "Polícia Civil",
            "endereco": "Rua da Aurora, 487 - Santo Amaro, Recife - PE",
            "latitude": -8.0582,
            "longitude": -34.8815,
            "telefone": "(81) 3184-3450",
            "atendimento_24h": True
        },
        {
            "nome": "1ª Delegacia da Mulher (DEAM Recife)",
            "tipo": "Delegacia da Mulher",
            "endereco": "Praça do Campo Santo, s/n - Santo Amaro, Recife - PE",
            "latitude": -8.0512,
            "longitude": -34.8885,
            "telefone": "(81) 3184-3352",
            "atendimento_24h": True
        },
        {
            "nome": "02ª Delegacia do Espinheiro",
            "tipo": "Polícia Civil",
            "endereco": "Rua da Hora, 853 - Espinheiro, Recife - PE",
            "latitude": -8.0435,
            "longitude": -34.8962,
            "telefone": "(81) 3184-3470",
            "atendimento_24h": True
        },
        {
            "nome": "07ª Delegacia de Boa Viagem",
            "tipo": "Polícia Civil",
            "endereco": "Av. Domingos Ferreira, 4420 - Boa Viagem, Recife - PE",
            "latitude": -8.1258,
            "longitude": -34.9025,
            "telefone": "(81) 3184-3530",
            "atendimento_24h": True
        },
        {
            "nome": "09ª Delegacia do Varadouro (Olinda)",
            "tipo": "Polícia Civil",
            "endereco": "Av. Sigismundo Gonçalves, 305 - Varadouro, Olinda - PE",
            "latitude": -7.9995,
            "longitude": -34.8510,
            "telefone": "(81) 3184-3580",
            "atendimento_24h": True
        }
    ]


ZONAS_RISCO = [
    {"nome": "Trecho Crítico / Baixa Iluminação", "latitude": -8.0535, "longitude": -34.8910, "raio": 180}
]


# ==============================================================================
# 3. CÁLCULO DE DISTÂNCIA E ENCONTRAR A DELEGACIA MAIS PROXIMA
# ==============================================================================
def distancia_haversine(coord1, coord2):
    """Calcula a distância em metros entre duas coordenadas (lat, lon)."""
    R = 6371000  # Raio da Terra em metros
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def encontrar_delegacia_mais_proxima(origem, delegacias):
    """Retorna a delegacia com a menor distância da origem."""
    mais_proxima = None
    menor_distancia = float("inf")

    for d in delegacias:
        dist = distancia_haversine(origem, (d["latitude"], d["longitude"]))
        if dist < menor_distancia:
            menor_distancia = dist
            mais_proxima = d
            mais_proxima["distancia_metros"] = dist

    return mais_proxima


# ==============================================================================
# 4. MOTOR DE ROTA VIÁRIA (OSRM API)
# ==============================================================================
def obter_rota_viaria(origem, destino):
    """Consulta o serviço público OSRM para traçar a rota viária pelas ruas."""
    url = f"https://router.project-osrm.org/route/v1/driving/{origem[1]},{origem[0]};{destino[1]},{destino[0]}"
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            dados = resp.json()
            if dados.get("routes"):
                rota = dados["routes"][0]
                # Converte GeoJSON [lon, lat] para formato do Folium [lat, lon]
                coordenadas = [(p[1], p[0]) for p in rota["geometry"]["coordinates"]]
                return {
                    "coordenadas": coordenadas,
                    "distancia_metros": rota["distance"],
                    "duracao_segundos": rota["duration"]
                }
    except Exception as e:
        print(f"Aviso: Não foi possível obter rota via OSRM ({e}). Usando linha direta.")

    # Fallback caso esteja sem internet ou API instável
    return {
        "coordenadas": [origem, destino],
        "distancia_metros": distancia_haversine(origem, destino),
        "duracao_segundos": distancia_haversine(origem, destino) / 8.5
    }


# ==============================================================================
# 5. GERADOR DO MAPA INTERATIVO COM FOLIUM
# ==============================================================================
def gerar_mapa_rota_segura(origem):
    delegacias = carregar_delegacias()
    delegacia_alvo = encontrar_delegacia_mais_proxima(origem, delegacias)
    destino = [delegacia_alvo["latitude"], delegacia_alvo["longitude"]]

    print(f"Ponto de Partida: {origem}")
    print(f"Delegacia Mais Próxima: {delegacia_alvo['nome']}")
    print(f"Endereço: {delegacia_alvo['endereco']}")
    print(f"Telefone: {delegacia_alvo['telefone']}")

    # Calcula a rota pelas ruas
    dados_rota = obter_rota_viaria(origem, destino)
    dist_km = dados_rota["distancia_metros"] / 1000.0
    tempo_min = int(dados_rota["duracao_segundos"] / 60)

    # Centro do mapa
    centro_lat = (origem[0] + destino[0]) / 2.0
    centro_lon = (origem[1] + destino[1]) / 2.0

    # Criação do mapa Folium
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=14,
        control_scale=True,
        tiles="OpenStreetMap"
    )

    # 1. Botão de Geolocalização em Tempo Real (GPS do dispositivo)
    LocateControl(
        auto_start=False,
        keepCurrentZoomLevel=True,
        drawMarker=True,
        flyTo=True,
        strings={"title": "Localizar minha posição atual", "popup": "Você está aqui"}
    ).add_to(mapa)

    # 2. Marcador do Ponto de Partida (Usuário)
    folium.Marker(
        location=origem,
        tooltip="Ponto de Partida (Você)",
        popup=folium.Popup(
            f"<b>Sua Posição</b><br>Coordenadas: {origem[0]:.4f}, {origem[1]:.4f}",
            max_width=250
        ),
        icon=folium.Icon(color="green", icon="user", prefix="fa")
    ).add_to(mapa)

    # 3. Marcador da Delegacia Destino
    status_plantao = "24 Horas" if delegacia_alvo.get("atendimento_24h") else "Horário Comercial"
    folium.Marker(
        location=destino,
        tooltip=f"Destino Seguro: {delegacia_alvo['nome']}",
        popup=folium.Popup(
            f"""
            <div style="font-family: Arial; min-width: 220px;">
                <h4 style="color: #0D47A1; margin: 0 0 5px 0;">{delegacia_alvo['nome']}</h4>
                <p style="margin: 3px 0; font-size: 12px;"><b>Tipo:</b> {delegacia_alvo.get('tipo', 'Polícia')}</p>
                <p style="margin: 3px 0; font-size: 12px;"><b>Plantão:</b> <span style="color: green; font-weight: bold;">{status_plantao}</span></p>
                <p style="margin: 3px 0; font-size: 12px;"><b>Endereço:</b> {delegacia_alvo['endereco']}</p>
                <p style="margin: 3px 0; font-size: 12px;"><b>Telefone:</b> <a href="tel:{delegacia_alvo['telefone']}">{delegacia_alvo['telefone']}</a></p>
            </div>
            """,
            max_width=300
        ),
        icon=folium.Icon(color="blue", icon="shield", prefix="fa")
    ).add_to(mapa)

    # 4. Zonas de Atenção / Risco no Mapa
    for z in ZONAS_RISCO:
        folium.Circle(
            location=[z["latitude"], z["longitude"]],
            radius=z["raio"],
            color="#D32F2F",
            fill=True,
            fill_color="#D32F2F",
            fill_opacity=0.25,
            tooltip=f"{z['nome']} (Área Monitorada)"
        ).add_to(mapa)

    # 5. Traçado da Rota Segura (PolyLine Verde Protegido)
    folium.PolyLine(
        locations=dados_rota["coordenadas"],
        color="#00897B",
        weight=6,
        opacity=0.9,
        tooltip=f"Rota Segura: {dist_km:.2f} km (~{tempo_min} min)"
    ).add_to(mapa)

    # 6. Painel Flutuante com Métricas e Botões de Emergência
    painel_html = f"""
    <div style="
        position: fixed;
        bottom: 25px;
        left: 25px;
        width: 310px;
        background: rgba(255, 255, 255, 0.96);
        backdrop-filter: blur(6px);
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.25);
        padding: 14px;
        font-family: Arial, sans-serif;
        z-index: 1000;
        border-left: 6px solid #00897B;
    ">
        <h4 style="margin: 0 0 6px 0; color: #1A237E; display: flex; justify-content: space-between;">
            <span>Rota Segura PE</span>
            <span style="font-size: 12px; background: #E8F5E9; color: #2E7D32; padding: 2px 6px; border-radius: 4px;">Ativo</span>
        </h4>
        <div style="font-size: 13px; color: #333; line-height: 1.4; margin-bottom: 8px;">
            <b>Destino:</b> {delegacia_alvo['nome']}<br>
            <b>Distância:</b> {dist_km:.2f} km | <b>Tempo estimado:</b> ~{tempo_min} min
        </div>
        <div style="border-top: 1px solid #ddd; padding-top: 8px;">
            <span style="font-size: 11px; font-weight: bold; color: #555;">DISCAGEM RÁPIDA DE EMERGÊNCIA:</span>
            <div style="display: flex; gap: 6px; margin-top: 5px;">
                <a href="tel:190" style="flex:1; text-align:center; background:#D32F2F; color:white; padding:5px 0; border-radius:4px; text-decoration:none; font-weight:bold; font-size:12px;">190 PM</a>
                <a href="tel:180" style="flex:1; text-align:center; background:#7B1FA2; color:white; padding:5px 0; border-radius:4px; text-decoration:none; font-weight:bold; font-size:12px;">180 Mulher</a>
                <a href="tel:197" style="flex:1; text-align:center; background:#1976D2; color:white; padding:5px 0; border-radius:4px; text-decoration:none; font-weight:bold; font-size:12px;">197 Civil</a>
            </div>
        </div>
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(painel_html))

    return mapa


# ==============================================================================
# 6. EXECUÇÃO
# ==============================================================================
if __name__ == "__main__":
    mapa_gerado = gerar_mapa_rota_segura(PONTO_ORIGEM)

    # Salva o arquivo HTML e abre no navegador
    nome_arquivo = "mapa_rota_segura.html"
    mapa_gerado.save(nome_arquivo)
    print(f"Mapa interativo salvo com sucesso em: {nome_arquivo}")

    webbrowser.open("https://www.bing.com/maps")
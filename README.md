# Backend del Predictor Mundial 2026

Este es el servidor que hace lo que el archivo HTML no puede hacer solo:
consultar resultados reales cada pocas horas, reentrenar el modelo, y
guardar el estado — sin que nadie tenga que abrir nada.

## 1. Consigue una API key de resultados de fútbol (gratis)

1. Ve a **https://www.api-football.com/** (también disponible vía RapidAPI)
2. Crea una cuenta → plan **Free** (100 requests/día, de sobra para refrescar
   cada 6 horas = 4 requests/día)
3. Copia tu API key

> Si prefieres otro proveedor (football-data.org, SportMonks, etc.) puedes
> reemplazar `data_provider.py` — solo tiene que devolver la misma
> estructura de datos que ya usa `fetch_fixtures()`.

## 2. Probarlo en tu computador

```bash
cd wc26-backend
pip install -r requirements.txt
export API_FOOTBALL_KEY="tu_key_aqui"
uvicorn main:app --reload
```

Abre `http://localhost:8000/api/state` en el navegador — deberías ver el
JSON con el ranking y las predicciones actuales.

Para forzar una actualización manual (sin esperar las 6 horas):
```bash
curl -X POST http://localhost:8000/api/refresh
```

## 3. Desplegarlo para que corra solo, 24/7

Un archivo HTML no puede hacer esto — necesitas un servidor que esté
siempre prendido. Opciones gratuitas o casi gratuitas:

### Opción A — Render.com (la más simple)
1. Sube esta carpeta a un repositorio de GitHub
2. En Render: **New → Web Service** → conecta el repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. En **Environment**, agrega la variable `API_FOOTBALL_KEY`
6. Deploy. Render te da una URL tipo `https://tu-app.onrender.com`

> El plan gratuito de Render "duerme" el servicio si no recibe tráfico
> por un rato — para que el refresh programado no se salte ciclos, puedes
> usar un servicio gratuito como **cron-job.org** para hacerle ping a
> `/health` cada pocos minutos y mantenerlo despierto.

### Opción B — Railway.app o Fly.io
Mismo proceso: conectas el repo, agregas la variable de entorno
`API_FOOTBALL_KEY`, y usas el mismo start command.

## 4. Conectar el archivo HTML a este backend

En `predictor-mundial-2026.html`, cambia la constante `API_BASE_URL` al
inicio del `<script>` por la URL de tu backend desplegado, por ejemplo:

```js
const API_BASE_URL = "https://tu-app.onrender.com";
```

Con eso, la app deja de usar los datos fijos y en vez de eso hace
`fetch(API_BASE_URL + "/api/state")` cada vez que la abres — mostrando
siempre lo último que el backend entrenó.

## Qué hace el refresh automático, en resumen

Cada `REFRESH_HOURS` horas (por defecto 6, configurable con esa variable
de entorno):
1. Pide los partidos del Mundial a la API de datos.
2. Si un partido que teníamos como "programado" ya tiene marcador final,
   reentrena el Elo y el ataque/defensa de ambos equipos.
3. Si aparece un cruce de eliminatoria que no existía antes (por ejemplo
   una llave de octavos que se acababa de definir), lo agrega solo.
4. Guarda todo en `state.json`.

## Límites honestos

- El mapeo de nombres de equipo (`TEAM_NAME_TO_CODE` en `data_provider.py`)
  puede necesitar ajustes si la API devuelve un nombre distinto al
  esperado — revisa los logs del servidor tras el primer refresh real.
- Si el partido termina en penales, el marcador que reentrena el modelo es
  el del tiempo reglamentario (90+ minutos), no la tanda de penales —
  es lo correcto para el modelo de goles, aunque el avance de ronda del
  equipo sí sea el que ganó por penales.
- Esto sigue siendo un modelo propio ilustrativo, no una fuente oficial.

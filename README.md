# Aviso WhatsApp lavadora / secadora (Tapo P110 + GitHub Actions + CallMeBot)

## 1. WhatsApp (una vez cada persona, desde su móvil)
Guarda el contacto de CallMeBot que figura en https://www.callmebot.com/blog/free-api-whatsapp-messages/ y envíale
`I allow callmebot to send me messages`. Te responde con tu **apikey**.

## 2. Repositorio **público** en GitHub con estos ficheros
(público = minutos de Actions ilimitados; en privado el cron de 5 min agota el cupo gratuito).
En Settings → Secrets and variables → Actions:

Secrets:
- `TAPO_EMAIL`, `TAPO_PASSWORD`: tu cuenta de la app Tapo (si tiene verificación en dos pasos, crea otra cuenta
  y compártele los enchufes desde la app).
- `WHATSAPP_RECIPIENTS`: `34600111222:APIKEY1,34699888777:APIKEY2`

Variables (nombre exacto del enchufe en la app Tapo):
- `WASHER_ALIAS`, `DRYER_ALIAS`

## 3. Probar
Actions → "Aviso lavadora y secadora" → Run workflow con `diagnose` marcado. Debe listar tus enchufes
y mostrar la potencia en bruto. Después se ejecuta solo cada 5 min.

## Ajuste
Umbrales en `APPLIANCES` de `monitor.py` (derivados de tus Excel): start_w, idle_w, idle_min.

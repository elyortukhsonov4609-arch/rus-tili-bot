#!/usr/bin/env bash
# Serverga (Ubuntu) botni o'rnatish va 24/7 ishlaydigan qilish.
# Ishlatish:  bash install.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
USER_NAME="$(whoami)"

echo "==> Kerakli dasturlar o'rnatilmoqda..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git tzdata

echo "==> Python muhiti tayyorlanmoqda..."
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  echo
  echo "Quyidagilarni kiriting (token va baza manzili yozilayotganda ekranda ko'rinmaydi — bu normal):"
  read -r -s -p "BotFather bergan TOKEN: " TOKEN; echo
  read -r -p "Sizning Telegram ID raqamingiz: " ADMIN
  read -r -s -p "Neon baza manzili (postgresql://... ; bo'sh qoldirsangiz — serverdagi lokal baza): " DBURL; echo
  {
    printf "BOT_TOKEN=%s\nADMIN_IDS=%s\nTIMEZONE=Asia/Tashkent\n" "$TOKEN" "$ADMIN"
    if [ -n "$DBURL" ]; then printf "DATABASE_URL=%s\n" "$DBURL"; fi
  } > .env
  chmod 600 .env
fi

echo "==> Avtomatik ishga tushish sozlanmoqda (systemd)..."
sudo tee /etc/systemd/system/rus-tili-bot.service > /dev/null <<UNIT
[Unit]
Description=Rus tili test boti
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=${DIR}
ExecStart=${DIR}/venv/bin/python ${DIR}/main.py
Restart=always
RestartSec=5
User=${USER_NAME}

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable rus-tili-bot
sudo systemctl restart rus-tili-bot
sleep 3
sudo systemctl --no-pager status rus-tili-bot | head -n 5
echo
echo "✅ Tayyor! Bot ishlayapti va server qayta yoqilsa ham o'zi ishga tushadi."
echo "   Holatini ko'rish:   sudo systemctl status rus-tili-bot"
echo "   Jurnal (log):       sudo journalctl -u rus-tili-bot -f"
echo "   Qayta ishga tushirish: sudo systemctl restart rus-tili-bot"

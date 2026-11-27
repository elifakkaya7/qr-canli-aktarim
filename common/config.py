"""Gönderici ve alıcının ortak ayarları.

"""

# --- Portlar (hepsi UDP) ---
VIDEO_PORT = 5000   # RTP/H.264 görüntü: gönderici -> alıcı
QR_PORT = 5001      # QR sonucu (JSON): gönderici -> alıcı
ACK_PORT = 5002     # Gecikme ölçümü yanıtı (kare_no): alıcı -> gönderici

# --- Görüntü ---
WIDTH = 640
HEIGHT = 480
FPS = 30

# --- H.264 kodlayıcı varsayılanları (komut satırından değiştirilebilir) ---
BITRATE_KBPS = 1500   # saniyede kilobit hedefi
KEY_INT_MAX = 30      # kaç karede bir tam kare (anahtar kare)

# --- RTP ---
RTP_PAYLOAD = 96      # gönderici (pt=96) ve alıcı (payload=96) aynı olmalı

# --- QR JSON mesajının alan adları ---
# Örnek mesaj:
# {"kare_no": 152, "zaman": 1764240000.123,
#  "qr_metinleri": ["https://ornek.com"],
#  "koseler": [[[10, 20], [110, 20], [110, 120], [10, 120]]]}
KEY_FRAME_NO = "kare_no"        # int, göndericideki kare sayacı
KEY_TIME = "zaman"              # float, göndericinin time.time() değeri
KEY_TEXTS = "qr_metinleri"      # list[str], QR yoksa boş liste
KEY_CORNERS = "koseler"         # list[list[[x, y] x4]], her QR için 4 köşe

# Alıcı bu süreden eski QR bilgisini çizmez (saniye)
QR_MAX_AGE_S = 0.5

# UDP mesajı için okuma tamponu (bayt)
UDP_BUFFER = 65535

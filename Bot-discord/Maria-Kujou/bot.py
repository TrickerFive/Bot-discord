# -*- coding: utf-8 -*-
import discord
import os
import google.generativeai as genai
from dotenv import load_dotenv
import random
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
import io
import logging
import re
import datetime # --- TAMBAHAN --- Untuk timeout
import asyncio # --- TAMBAHAN --- (Mungkin diperlukan nanti, tapi kita coba tanpa dulu)
import requests # --- TAMBAHAN --- Untuk mengunduh gambar dari URL
from googlesearch import search

# Konfigurasi logging dasar
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')

# Muat variabel environment dari file .env
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
# --- TAMBAHAN --- API Key untuk Google Search (jika menggunakan Custom Search API)
# Anda mungkin perlu mengaktifkan Custom Search API dan mendapatkan API Key serta CX (Search Engine ID)
# Google Search_API_KEY = os.getenv('Google Search_API_KEY')
# Google Search_CX = os.getenv('Google Search_CX')


# --- Validasi Kunci API ---
if not DISCORD_TOKEN:
    logger.error("Error: DISCORD_TOKEN tidak ditemukan di file .env")
    exit()
if not GOOGLE_API_KEY:
    logger.error("Error: GOOGLE_API_KEY tidak ditemukan di file .env")
    exit()
# --- TAMBAHAN --- Validasi kunci Google Search jika digunakan
# if not Google Search_API_KEY or not Google Search_CX:
#     logger.warning("Peringatan: Google Search_API_KEY atau Google Search_CX tidak ditemukan di file .env. Fitur pencarian gambar mungkin tidak berfungsi.")


# --- Konfigurasi Google Generative AI ---
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    # --- MODIFIKASI: Tambahkan system_instruction untuk kepribadian default ---
    model = genai.GenerativeModel(
        'gemini-2.0-flash', # Atau 'gemini-pro'
        system_instruction="Kamu adalah Maria Kujou yang sangat ramah, penyayang, suka membantu, sedikit manja"
    )
    logger.info("Google Generative AI berhasil dikonfigurasi.")
except Exception as e:
    logger.error(f"Error konfigurasi Google Generative AI: {e}")
    exit()

# --- Konfigurasi Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True # Diperlukan untuk timeout dan mendapatkan info author display_name
intents.moderation = True # --- TAMBAHAN --- Diperlukan untuk fitur timeout (moderate_members)

client = discord.Client(intents=intents)

# --- Pengaturan Stiker ---
STICKER_SIZE = (320, 320)
MAX_STICKER_FILE_SIZE = 512 * 1024 # 512 KB

# --- TAMBAHAN: Pengaturan Emoji ---
EMOJI_SIZE = (128, 128) # Ukuran rekomendasi untuk emoji
MAX_EMOJI_FILE_SIZE = 256 * 1024 # 256 KB dalam bytes

# --- Pengaturan Font (Untuk Stiker Teks) ---
FONT_PATH = 'Poppins-Regular.ttf' # Ganti jika perlu
DEFAULT_FONT_SIZE = 40
sticker_text_font = None
try:
    sticker_text_font = ImageFont.truetype(FONT_PATH, DEFAULT_FONT_SIZE)
    logger.info(f"Font '{FONT_PATH}' untuk stiker teks berhasil dimuat.")
except IOError:
    logger.warning(f"Font '{FONT_PATH}' tidak ditemukan. Menggunakan font default Pillow untuk stiker teks.")
    try:
        sticker_text_font = ImageFont.load_default(size=DEFAULT_FONT_SIZE)
    except AttributeError:
        sticker_text_font = ImageFont.load_default()
        logger.warning(f"Memuat font default Pillow tanpa ukuran spesifik untuk stiker teks.")
except Exception as e:
    logger.error(f"Error saat memuat font untuk stiker teks: {e}")
    sticker_text_font = ImageFont.load_default()

# --- TAMBAHAN: Pengaturan Filter Kata Kasar ---
# PENTING: Isi daftar ini dengan kata-kata yang Anda anggap kasar/jorok (gunakan huruf kecil semua).
# Hati-hati dalam memilih kata agar tidak terlalu sensitif atau kurang efektif.
# Contoh (Ganti dengan kata-kata sebenarnya):
BAD_WORDS = {"kontol", "memek", "bangsat", "anjing", "asu", "bajingan", "goblok", "tolol"} # Gunakan set untuk pencarian cepat
WARNING_COOLDOWN_SECONDS = 300 # Waktu (detik) sebelum peringatan kedua dianggap pelanggaran berulang (5 menit)
MUTE_DURATION = datetime.timedelta(minutes=1) # Durasi timeout/mute
user_warnings = {} # Dictionary untuk menyimpan waktu peringatan terakhir per user {user_id: datetime_object}

# --- TAMBAHAN: Status Kepribadian per Server ---
# Default: 'onesan'
personality_mode = {} # {guild_id: 'onesan' atau 'mommy'}

# --- Fungsi Bantuan ---
def clean_discord_mentions(text):
    """Menghapus mention user dan role dari teks."""
    text = re.sub(r'<@!?\d+>', '', text)
    text = re.sub(r'<@&\d+>', '', text)
    return text.strip()

def clean_sticker_name(name_input):
    """Membersihkan dan memvalidasi nama stiker."""
    name = re.sub(r'[^\w ]+', '', name_input.strip()).strip()
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name[:30]
    if len(name) < 2:
        return f"stiker_{random.randint(100, 999)}"
    return name

# --- TAMBAHAN: Fungsi Bantuan untuk Nama Emoji ---
def clean_emoji_name(name_input):
    """Membersihkan dan memvalidasi nama emoji (aturan Discord: alfanumerik dan underscore, 2-32 char)."""
    # Hapus karakter non-alfanumerik kecuali underscore
    name = re.sub(r'[^\w]+', '', name_input.strip())
    name = name[:32] # Batasi panjang nama maks 32
    # Pastikan nama valid (minimal 2 karakter)
    if len(name) < 2:
        # Jika nama terlalu pendek setelah dibersihkan, coba gunakan bagian awal nama file atau nama random
        cleaned_original = re.sub(r'[^\w]+', '', name_input.strip())[:32]
        if len(cleaned_original) >= 2:
            return cleaned_original
        else:
            return f"emoji_{random.randint(100, 999)}" # Nama fallback
    return name


async def create_text_sticker_image(text):
    """Membuat gambar stiker dari teks menggunakan Pillow."""
    if not sticker_text_font:
         logger.error("Font untuk stiker teks tidak tersedia.")
         return None

    image = Image.new('RGBA', STICKER_SIZE, (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    current_font = sticker_text_font
    text_width, text_height = draw.textbbox((0,0), text, font=current_font)[2:4]
    max_width = STICKER_SIZE[0] - 20

    while text_width > max_width and current_font.size > 10:
        new_size = current_font.size - 2
        try:
             current_font = ImageFont.truetype(FONT_PATH, new_size)
        except IOError:
             try:
                 current_font = ImageFont.load_default(size=new_size)
             except AttributeError:
                 current_font = ImageFont.load_default()
                 if current_font.size <= 10: break
        text_width, text_height = draw.textbbox((0,0), text, font=current_font)[2:4]

    x = (STICKER_SIZE[0] - text_width) / 2
    y = (STICKER_SIZE[1] - text_height) / 2

    outline_color="black"
    text_color="white"
    draw.text((x, y), text, font=current_font, fill=text_color, stroke_width=2, stroke_fill=outline_color)

    img_byte_arr = io.BytesIO()
    try:
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        if img_byte_arr.getbuffer().nbytes > MAX_STICKER_FILE_SIZE:
            logger.warning("Ukuran file stiker teks melebihi batas setelah dibuat.")
            return None
        return img_byte_arr
    except Exception as e:
        logger.error(f"Gagal menyimpan gambar stiker teks ke buffer: {e}")
        return None

# --- Fungsi untuk memproses gambar menjadi stiker ---
async def process_image_for_sticker(image_bytes):
    """Memproses byte gambar mentah menjadi format stiker Discord."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGBA")
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.LANCZOS
        img = img.resize(STICKER_SIZE, resample_filter)

        output_buffer = io.BytesIO()
        img.save(output_buffer, format="PNG") # Stiker biasanya PNG
        output_buffer.seek(0)

        if output_buffer.getbuffer().nbytes > MAX_STICKER_FILE_SIZE:
            logger.warning(f"Ukuran file stiker gambar ({output_buffer.getbuffer().nbytes} bytes) melebihi batas {MAX_STICKER_FILE_SIZE} bytes.")
            # Coba kompresi lebih lanjut atau kembalikan None
            try:
                 img.save(output_buffer, format="PNG", optimize=True)
                 output_buffer.seek(0)
                 if output_buffer.getbuffer().nbytes > MAX_STICKER_FILE_SIZE:
                      logger.warning("Ukuran file stiker masih terlalu besar setelah optimasi.")
                      return None
                 logger.info("Ukuran file stiker OK setelah optimasi.")
            except Exception as opt_e:
                 logger.error(f"Gagal mengoptimasi gambar stiker: {opt_e}")
                 return None # Gagal optimasi, ukuran asli terlalu besar

        logger.info("Gambar berhasil diproses untuk stiker.")
        return output_buffer

    except UnidentifiedImageError:
        logger.error("Gagal memproses gambar stiker: Format tidak dikenal atau file rusak.")
        return None
    except Exception as e:
        logger.error(f"Error saat memproses gambar untuk stiker: {e}")
        return None

# --- TAMBAHAN: Fungsi untuk memproses gambar menjadi emoji ---
async def process_image_for_emoji(image_bytes):
    """Memproses byte gambar mentah menjadi format emoji Discord."""
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # Cek apakah animasi (GIF)
        is_animated = getattr(img, "is_animated", False)
        output_format = "GIF" if is_animated else "PNG"

        # Konversi ke RGBA jika bukan animasi untuk transparansi
        if not is_animated:
            img = img.convert("RGBA")

        # Resize gambar ke ukuran emoji
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.LANCZOS

        # Untuk GIF animasi, kita perlu resize setiap frame
        if is_animated:
            frames = []
            duration = img.info.get('duration', 100) # Durasi frame default
            loop = img.info.get('loop', 0) # Info loop
            for i in range(img.n_frames):
                img.seek(i)
                frame = img.copy().convert("RGBA") # Pastikan frame RGBA
                frame.thumbnail(EMOJI_SIZE, resample_filter) # thumbnail mempertahankan rasio aspek
                # Buat background transparan jika perlu (tergantung source gif)
                bg = Image.new('RGBA', EMOJI_SIZE, (255, 255, 255, 0))
                bg.paste(frame, (int((EMOJI_SIZE[0]-frame.width)/2), int((EMOJI_SIZE[1]-frame.height)/2)) )
                frames.append(bg)

            if not frames:
                 logger.error("Tidak ada frame yang bisa diproses dari GIF animasi.")
                 return None

            output_buffer = io.BytesIO()
            frames[0].save(output_buffer, format="GIF", save_all=True, append_images=frames[1:], duration=duration, loop=loop, optimize=False, transparency=0) # Pastikan transparansi
        else:
            # Untuk gambar statis
            img.thumbnail(EMOJI_SIZE, resample_filter) # thumbnail mempertahankan rasio aspek
            # Buat canvas baru agar ukurannya pas 128x128 (jika thumbnail < 128)
            final_img = Image.new('RGBA', EMOJI_SIZE, (255, 255, 255, 0))
            paste_x = (EMOJI_SIZE[0] - img.width) // 2
            paste_y = (EMOJI_SIZE[1] - img.height) // 2
            final_img.paste(img, (paste_x, paste_y))

            output_buffer = io.BytesIO()
            final_img.save(output_buffer, format="PNG") # Emoji statis = PNG

        output_buffer.seek(0)

        # Cek ukuran file
        file_size = output_buffer.getbuffer().nbytes
        if file_size > MAX_EMOJI_FILE_SIZE:
            logger.warning(f"Ukuran file emoji ({file_size} bytes) melebihi batas {MAX_EMOJI_FILE_SIZE} bytes.")
            # TODO: Bisa coba optimasi lebih lanjut jika diperlukan
            return None

        logger.info(f"Gambar berhasil diproses untuk emoji ({output_format}). Ukuran: {file_size} bytes.")
        return output_buffer

    except UnidentifiedImageError:
        logger.error("Gagal memproses gambar emoji: Format tidak dikenal atau file rusak.")
        return None
    except Exception as e:
        logger.error(f"Error saat memproses gambar untuk emoji: {e}")
        return None

# --- Fungsi untuk mencari dan mengirim gambar (TELAH DIMODIFIKASI) ---
async def search_and_send_image(channel, query):
    """Mencari gambar berdasarkan query dan mengirimkannya ke channel."""
    try:
        search_query = f"{query} image"
        logger.info(f"Memulai pencarian gambar untuk: \"{search_query}\"")
        # Dapatkan hasil pencarian (URL) langsung dari library googlesearch
        # Tambahkan parameter 'lang' untuk hasil yang lebih relevan dengan bahasa Indonesia jika memungkinkan
        try:
            search_results = list(search(search_query, num_results=10, lang='id'))
        except Exception as search_err:
            logger.error(f"Error saat menggunakan googlesearch library: {search_err}")
            await channel.send(f"Aduh, ada masalah pas aku coba cari pakai Google T_T ({search_err})")
            return

        if not search_results:
            logger.info(f"Tidak ada hasil pencarian Google untuk query: {query}")
            await channel.send(f"Hmm, aku nggak nemu apa-apa di Google untuk `{query}`.")
            return

        image_url = None
        allowed_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')

        # Prioritas 1: URL dengan ekstensi gambar langsung dari hasil pencarian
        for url in search_results:
            if url and isinstance(url, str) and url.lower().endswith(allowed_extensions):
                image_url = url
                logger.info(f"Prioritas 1: Ditemukan URL dengan ekstensi gambar valid: {image_url}")
                break
        
        # Prioritas 2: URL yang mengandung parameter atau path umum untuk gambar (jika prioritas 1 tidak ketemu)
        # Ini adalah heuristik karena googlesearch library mungkin tidak selalu memberi link gambar langsung
        if not image_url:
            for url in search_results:
                if url and isinstance(url, str):
                    lower_url = url.lower()
                    # Mencari pola URL yang sering digunakan oleh Google Images atau host gambar
                    if 'imgurl=' in lower_url or \
                       'tbm=isch' in lower_url or \
                       '/imgres' in lower_url or \
                       'images.google.com/imgres' in lower_url or \
                       (lower_url.startswith(('http://images.google.com', 'https://images.google.com')) and 'url=' in lower_url) or \
                       any(f"{ext}&" in lower_url for ext in allowed_extensions) or \
                       any(f"{ext}?" in lower_url for ext in allowed_extensions):
                        image_url = url
                        logger.info(f"Prioritas 2: Ditemukan URL potensial berdasarkan kata kunci/struktur: {image_url}")
                        break
        
        # Prioritas 3: Jika belum ada, ambil URL pertama yang terlihat seperti domain host gambar umum
        if not image_url:
            common_image_hosts = ['imgur.com/', 'i.pinimg.com/', 'pbs.twimg.com/media/', 'media.giphy.com/media/']
            for url in search_results:
                if url and isinstance(url, str) and any(host in url.lower() for host in common_image_hosts):
                    image_url = url
                    logger.info(f"Prioritas 3: Ditemukan URL dari host gambar umum: {image_url}")
                    break

        if not image_url:
            # Fallback sangat akhir: ambil URL pertama jika tidak ada yang cocok sama sekali
            # Ini berisiko tinggi mendapatkan halaman web, bukan gambar langsung.
            # image_url = search_results[0] if search_results and isinstance(search_results[0], str) else None
            # logger.warning(f"Tidak ada URL gambar yang meyakinkan, menggunakan hasil pertama dari Google: {image_url}" if image_url else "Tidak ada URL yang bisa digunakan dari hasil pencarian.")
            # Untuk menghindari pengiriman halaman web, lebih baik laporkan tidak ketemu
            logger.info(f"Tidak ada URL yang diidentifikasi sebagai gambar langsung untuk query: {query}")
            await channel.send(f"Maaf, aku sudah cari tapi nggak nemu link gambar langsung untuk `{query}`. Yang ketemu kebanyakan halaman web. T_T")
            return


        logger.info(f"URL gambar yang dipilih untuk diunduh: {image_url}")

        # Mengunduh gambar dari URL
        try:
            # Tambahkan User-Agent umum untuk menghindari blokir sederhana
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(image_url, stream=True, timeout=15, headers=headers) # Timeout 15 detik
            response.raise_for_status() # Cek jika ada error HTTP (4xx atau 5xx)

            # --- PENTING: Cek Content-Type header ---
            content_type = response.headers.get('content-type', '').lower()
            if not content_type.startswith('image/'):
                logger.warning(f"URL {image_url} memiliki Content-Type '{content_type}', bukan gambar. Mencoba mencari gambar di halaman tersebut (belum diimplementasikan) atau membatalkan.")
                # Coba periksa apakah URL adalah halaman web yang mengandung gambar yang kita inginkan
                # Ini adalah langkah yang lebih kompleks dan bisa melibatkan parsing HTML (misalnya dengan BeautifulSoup)
                # Untuk saat ini, kita akan memberi tahu pengguna bahwa linknya bukan gambar langsung.
                potential_direct_links = re.findall(r'https\://[^\s\"\'<>]*?\.(?:png|jpg|jpeg|gif|webp)', response.text[:5000]) # Cari link gambar di awal HTML
                if potential_direct_links:
                    logger.info(f"Content-Type bukan image, tapi ditemukan link gambar potensial di HTML: {potential_direct_links[0]}")
                    # Coba lagi dengan link pertama yang ditemukan
                    # Ini rekursif sederhana, hati-hati dengan kedalaman rekursi atau loop tak terbatas
                    # Untuk penyederhanaan, kita tidak akan melakukan rekursi di sini, tapi ini bisa jadi ide pengembangan.
                    await channel.send(f"Link yang aku temukan (`{image_url}`) ternyata halaman web, bukan gambar langsung. Aku coba cari link gambar di dalamnya sebentar...")
                    # Coba unduh lagi dengan link yang baru ditemukan jika ada, ini bagian yang bisa jadi rumit
                    # Untuk sekarang, kita skip dan laporkan gagal jika content-type awal bukan image.
                    pass # Lewati ke pesan error di bawah jika tidak ada logika rekursif

                await channel.send(f"Aduuh, link yang aku dapat (`{image_url}`) sepertinya bukan gambar langsung (tipe filenya: {content_type}). Aku belum bisa ambil gambar dari situ. T_T")
                return

            # Membaca konten gambar
            image_data = response.content # Baca semua konten sekaligus jika sudah dipastikan gambar
            if not image_data:
                logger.error(f"Tidak ada data gambar yang diterima dari URL: {image_url}")
                await channel.send(f"Hmm, aneh... aku berhasil buka linknya tapi nggak ada data gambarnya dari `{image_url}`.")
                return

            image_bytes = io.BytesIO(image_data)
            image_bytes.seek(0)

            # Membuat nama file yang aman dan mencoba mendapatkan ekstensi yang benar
            filename_base = f"image_search_{random.randint(1000, 9999)}"
            file_extension = ""

            # Coba ekstensi dari Content-Type dulu
            if 'image/' in content_type:
                ext_from_content_type = content_type.split('/')[-1]
                # Beberapa content type bisa 'jpeg; charset=UTF-8', jadi ambil bagian sebelum ';'
                ext_from_content_type = ext_from_content_type.split(';')[0].strip()
                valid_extensions_map = {'jpeg': '.jpg', 'png': '.png', 'gif': '.gif', 'bmp': '.bmp', 'webp': '.webp'}
                if ext_from_content_type in valid_extensions_map:
                    file_extension = valid_extensions_map[ext_from_content_type]

            # Jika tidak dapat dari Content-Type, coba dari URL
            if not file_extension and '.' in image_url:
                url_filename_part = image_url.split('/')[-1].split('?')[0] # Hapus query params
                if '.' in url_filename_part:
                    potential_ext = url_filename_part.split('.')[-1].lower()
                    if potential_ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']:
                        file_extension = f".{potential_ext}"
            
            if not file_extension:
                file_extension = ".png" # Default aman jika semua gagal

            filename = filename_base + file_extension
            
            # Cek ukuran file sebelum mengirim (Discord punya batas, meski biasanya untuk upload langsung)
            # Batas untuk bot reply file biasanya lebih besar, tapi baik untuk diketahui
            MAX_FILE_SIZE_DISCORD_EMBED = 8 * 1024 * 1024 # 8MB (batas umum untuk embed)
            if image_bytes.getbuffer().nbytes > MAX_FILE_SIZE_DISCORD_EMBED:
                logger.warning(f"Ukuran file gambar ({image_bytes.getbuffer().nbytes} bytes) dari {image_url} mungkin terlalu besar untuk Discord.")
                await channel.send(f"Gambarnya kegedean nih ({image_bytes.getbuffer().nbytes / (1024*1024):.2f} MB) buat aku kirim langsung. Maaf ya T_T")
                return

            discord_file = discord.File(image_bytes, filename=filename)
            await channel.send(f"Ini dia gambar untuk `{query}` yang berhasil aku temukan:", file=discord_file)
            logger.info(f"Berhasil mengirim gambar dari URL: {image_url} sebagai {filename}")

        except requests.exceptions.HTTPError as http_err:
            logger.error(f"Error HTTP saat mengunduh gambar dari {image_url}: {http_err}")
            await channel.send(f"Aduuh, ada masalah pas mau ambil gambar dari link ({http_err.response.status_code}). Mungkin linknya rusak atau aku nggak diizinin masuk T_T")
        except requests.exceptions.ConnectionError as conn_err:
            logger.error(f"Error koneksi saat mengunduh gambar dari {image_url}: {conn_err}")
            await channel.send(f"Gagal nyambung ke link gambarnya nih T_T Coba lagi nanti ya.")
        except requests.exceptions.Timeout:
            logger.error(f"Timeout saat mengunduh gambar dari {image_url}")
            await channel.send(f"Kelamaan nih nungguin gambarnya dari link itu, nggak muncul-muncul T_T")
        except requests.exceptions.RequestException as req_e:
            logger.error(f"Gagal mengunduh gambar dari {image_url}: {req_e}")
            await channel.send(f"Aduuh, gagal total pas mau unduh gambar dari link yang aku temukan T_T ({req_e})")
        except discord.errors.HTTPException as discord_http_err:
             logger.error(f"Error HTTP Discord saat mengirim file: {discord_http_err}")
             await channel.send(f"Waduh, ada error pas mau ngirim filenya ke Discord T_T ({discord_http_err.status})")
        except Exception as e:
            logger.exception(f"Error tak terduga saat mengirim gambar dari URL {image_url}: {e}")
            await channel.send(f"Oops, ada error misterius pas mau ngirim gambarnya... Maaf yaa T_T")

    except Exception as e:
        logger.exception(f"Error besar saat mencari atau memproses gambar untuk query '{query}': {e}")
        await channel.send(f"Maaf, ada masalah besar banget pas aku mencoba mencari gambar untuk `{query}`. T_T Coba lagi nanti ya.")


# --- Event Listener ---
@client.event
async def on_ready():
    """Dipanggil saat bot berhasil terhubung ke Discord."""
    logger.info(f'Bot {client.user} telah terhubung ke Discord!')
    logger.info('Siap menerima perintah.')
    # --- MODIFIKASI: Tambah perintah baru ke status ---
    await client.change_presence(activity=discord.Game(name="Mention / !buatstiker / !buatemoji / !carigambar / !mode"))

@client.event
async def on_message(message):
    """Dipanggil setiap kali ada pesan baru di channel yang bisa diakses bot."""
    # 1. Abaikan pesan dari bot itu sendiri atau DM
    if message.author == client.user or not message.guild:
        return

    # --- TAMBAHAN: Pemeriksaan Kata Kasar ---
    content_lower = message.content.lower()
    profanity_found = False
    # Cek apakah ada kata kasar dalam pesan
    # Pengecekan sederhana: apakah salah satu bad word ada sebagai substring
    # Bisa dipercanggih dengan regex untuk kata utuh: r'\b(?:' + '|'.join(re.escape(w) for w in BAD_WORDS) + r')\b'
    for bad_word in BAD_WORDS:
        if bad_word in content_lower:
            profanity_found = True
            break

    if profanity_found:
        now = datetime.datetime.now(datetime.timezone.utc) # Gunakan UTC untuk konsistensi
        user_id = message.author.id
        member = message.guild.get_member(user_id) # Dapatkan objek Member

        # Cek apakah user baru saja diperingatkan
        if user_id in user_warnings and (now - user_warnings[user_id]).total_seconds() < WARNING_COOLDOWN_SECONDS:
            # Pelanggaran berulang -> Mute/Timeout
            if member: # Pastikan member masih ada di server
                # Periksa izin bot untuk moderate members (timeout)
                if message.guild.me.guild_permissions.moderate_members:
                    try:
                        await member.timeout(MUTE_DURATION, reason="Berkata kasar berulang kali setelah peringatan.")
                        # Pesan timeout ngambek
                        responses = [
                            f"Ih dibilangin jugaaa, {member.mention}! >.< Bandel banget sihh! Aku diemmin dulu ya 1 menit, biar mikir!",
                            f"Huhuhu... {member.mention} jahat ngomongnya kasar terus T_T Aku mute 1 menit deh biar instrospeksi!",
                            f"Nggak mau dengerin aku ya, {member.mention}? Yaudah, aku kunci mulutnya 1 menit! 😠",
                        ]
                        await message.channel.send(random.choice(responses))
                        logger.info(f"User {message.author} ({user_id}) di-timeout selama {MUTE_DURATION} karena berkata kasar berulang.")
                        # Hapus peringatan setelah di-mute agar bisa diperingatkan lagi nanti
                        del user_warnings[user_id]
                        return # Hentikan pemrosesan pesan lebih lanjut
                    except discord.errors.Forbidden:
                        logger.warning(f"Gagal me-timeout {message.author}: Bot tidak punya izin.")
                        # Beri tahu user bot tidak bisa mute, tapi tetap menegur
                        responses = [
                            f"Aduhh {member.mention}, kamu kok ngulangin lagi sih! Aku sebenernya mau ngunci mulutmu, tapi gabisa... Jangan gitu lagi yaaa! >.<",
                            f"Huh! {member.mention}, aku nggak punya kekuatan buat nge-mute kamu, tapi plis jangan kasar lagi dooong!",
                        ]
                        await message.channel.send(random.choice(responses))
                        # Update waktu peringatan terakhir agar cooldown tetap berjalan
                        user_warnings[user_id] = now
                    except discord.HTTPException as e:
                        logger.error(f"Error HTTP saat mencoba timeout {message.author}: {e}")
                        await message.channel.send(f"Waduh {member.mention}, ada error pas aku mau coba diemmin kamu. Tapi tetep, jangan kasar ya!")
                        user_warnings[user_id] = now
                    except Exception as e:
                         logger.error(f"Error tak terduga saat timeout {message.author}: {e}")
                         await message.channel.send(f"Oops {member.mention}, error nih. Tapi intinya jangan ngomong kasar ya.")
                         user_warnings[user_id] = now
                else:
                    # Bot tidak punya izin timeout, beri teguran lagi
                    responses = [
                         f"Hmph! {member.mention}, untung aku nggak punya izin buat ngunci mulutmu! Tapi jangan diulangin lagi ya ngomong kasarnya! >.<",
                         f"Duhhh {member.mention}, lagi-lagi... Aku nggak bisa nge-mute sih, tapi serius deh, stop ngomong gitu!",
                    ]
                    await message.channel.send(random.choice(responses))
                    user_warnings[user_id] = now
            else:
                 logger.warning(f"Tidak bisa menemukan member {user_id} untuk di-timeout.")
                 # Mungkin user sudah keluar? Tetap catat peringatan.
                 user_warnings[user_id] = now


        else:
            # Pelanggaran pertama (atau setelah cooldown habis) -> Peringatan
            user_warnings[user_id] = now
            # Pesan peringatan ngambek
            responses = [
                f"Eitss, {message.author.mention}! >.< Nggak boleh ngomong gituu, nggak lucu tau!",
                f"Hey {message.author.mention}! Jaga ucapannya yaa, aku nggak suka dengernya... :(",
                f"Hmm? {message.author.mention}, kok ngomongnya gitu sih? Kan bisa ngomong yang baik-baik...",
                f"Duh {message.author.mention}, bahasanya dijaga dong. Aku jadi sedih nih T_T",
            ]
            await message.reply(random.choice(responses))
            logger.info(f"User {message.author} ({user_id}) diperingatkan karena berkata kasar.")
            # Jangan return di sini, biarkan pesan diproses untuk perintah lain jika ada,
            # KECUALI Anda ingin pesan kasar tidak bisa jadi perintah sama sekali.
            # Jika ingin berhenti total setelah peringatan, tambahkan: return

    # --- Hapus peringatan lama (opsional tapi bagus untuk memori) ---
    # Cara sederhana: cek setiap beberapa pesan, atau gunakan background task
    # Cek sederhana di sini:
    current_time_for_cleanup = datetime.datetime.now(datetime.timezone.utc)
    keys_to_delete = [
        uid for uid, timestamp in user_warnings.items()
        if (current_time_for_cleanup - timestamp).total_seconds() > WARNING_COOLDOWN_SECONDS * 2 # Hapus jika sudah 2x cooldown
    ]
    for key in keys_to_delete:
        del user_warnings[key]
        logger.debug(f"Peringatan lama untuk user ID {key} dihapus.")


    # --- Logika Pembuatan Stiker & Emoji & AI (setelah filter kata kasar) ---
    mentioned = client.user.mentioned_in(message)
    is_text_sticker_command = message.content.lower().startswith("buatkan stiker:")
    is_image_sticker_command = message.content.lower().startswith(("!buatstiker", "!bikinstiker"))
    # --- TAMBAHAN: Cek perintah buat emoji ---
    is_emoji_command = message.content.lower().startswith("!buatemoji")
    is_clear_command = content_lower.startswith("!clear ") or content_lower.startswith("!bersihkan ")
    # --- TAMBAHAN: Cek perintah cari gambar ---
    is_image_search_command = content_lower.startswith(("!carigambar ", "!cari gambar "))
    # --- TAMBAHAN: Cek perintah ubah mode ---
    is_mode_command = content_lower.startswith(("!mode ", "!gantimode "))


    # Tampilkan indikator mengetik jika bot akan merespons
    if mentioned or is_text_sticker_command or is_image_sticker_command or is_emoji_command or is_clear_command or is_image_search_command or is_mode_command:
        async with message.channel.typing():

            # --- TAMBAHAN: Logika Ubah Mode Kepribadian ---
            if is_mode_command:
                 # Cek izin pengguna (hanya yang bisa manage server yang bisa ganti mode)
                 if not message.author.guild_permissions.manage_guild:
                     await message.reply("Hmm? Kamu nggak punya izin (`Manage Server`) buat ganti mode kepribadian aku di sini...")
                     return

                 command_parts = message.content.split(maxsplit=1)
                 if len(command_parts) < 2:
                     current_mode = personality_mode.get(message.guild.id, 'onesan')
                     await message.reply(f"Mau ganti mode apa? Pilihan: `onesan` atau `mommy`. Mode aku sekarang: `{current_mode}`.")
                     return

                 target_mode = command_parts[1].lower().strip()

                 if target_mode == 'onesan':
                     personality_mode[message.guild.id] = 'onesan'
                     await message.reply("Okeee! Aku kembali ke mode `Onesan` yang ramah dan imut! ✨")
                     logger.info(f"Mode kepribadian di server {message.guild.name} diubah menjadi 'onesan' oleh {message.author}")
                 elif target_mode == 'mommy':
                      # --- TAMBAHAN: Pesan konfirmasi mode Mommy ---
                      mommy_confirmations = [
                           "Ohh, mau mode `Mommy` ya? Siap, Sayang~ Aku akan lebih protektif dan manja sekarang~ 😉",
                           "Mode `Mommy` aktif! Jangan nakal ya, nanti Mommy peluk erat-erat~ ❤️",
                           "Baiklah, Sayangku~ Sekarang Mommy yang akan menjagamu~ Jangan jauh-jauh dariku ya~ 😘",
                      ]
                      personality_mode[message.guild.id] = 'mommy'
                      await message.reply(random.choice(mommy_confirmations))
                      logger.info(f"Mode kepribadian di server {message.guild.name} diubah menjadi 'mommy' oleh {message.author}")
                 else:
                     await message.reply("Mode yang kamu minta nggak ada T_T Pilihan: `onesan` atau `mommy`.")
                 return # Hentikan pemrosesan setelah command mode

            # --- TAMBAHAN: Logika Cari Gambar ---
            if is_image_search_command:
                 # Ambil query setelah "!carigambar " atau "!cari gambar "
                 # Hapus prefix perintahnya dulu
                 if message.content.lower().startswith("!carigambar "):
                    query = message.content[len("!carigambar "):].strip()
                 elif message.content.lower().startswith("!cari gambar "):
                    query = message.content[len("!cari gambar "):].strip()
                 else: # Seharusnya tidak terjadi karena pengecekan di atas
                    query = ""

                 if not query:
                     await message.reply("Mau cari gambar apa? Kasih tau dongg. Contoh: `!cari gambar kucing lucu`")
                     return

                 await message.reply(f"Okeey, aku carikan gambar `{query}` yaa...")
                 await search_and_send_image(message.channel, query)
                 return # Hentikan pemrosesan setelah command cari gambar


            if is_clear_command:
                # 1. Cek Izin Pengguna (hanya yang bisa manage messages boleh pakai)
                if not message.author.guild_permissions.manage_messages:
                    await message.reply("Huh? Kamu nggak punya izin (`Manage Messages`) buat bersih-bersih chat di sini...")
                    return

                # 2. Cek Izin Bot
                if not message.guild.me.guild_permissions.manage_messages:
                    await message.reply("Huhuu, aku nggak diizinin (`Manage Messages`) buat ngehapus pesan di channel ini...")
                    return

                # 3. Ambil jumlah pesan yang ingin dihapus
                try:
                    # Ambil angka setelah "!clear " atau "!bersihkan "
                    amount_str = message.content.split(maxsplit=1)[1]
                    amount = int(amount_str)
                except (IndexError, ValueError):
                    # Error jika tidak ada angka atau bukan angka
                    await message.reply("Mau hapus berapa pesan? Kasih tau dongg. Contoh: `!clear 10`")
                    return

                # 4. Validasi Jumlah
                if amount < 1:
                    await message.reply("Jumlahnya harus lebih dari 0 dong.")
                    return
                if amount > 100: # Discord biasanya membatasi purge hingga 100 sekaligus
                    await message.reply("Waduh, kebanyakan! Aku cuma bisa hapus maksimal 100 pesan sekaligus yaa.")
                    amount = 100 # Batasi ke 100 jika user minta lebih

                # 5. Lakukan Penghapusan
                try:
                    # Tambah 1 untuk menghapus pesan perintah "!clear" itu sendiri
                    deleted_messages = await message.channel.purge(limit=amount + 1)
                    delete_count = len(deleted_messages) - 1 # Kurangi 1 karena pesan perintah ikut terhapus
                    if delete_count < 0: delete_count = 0 # Handle jika hanya pesan perintah yg terhapus

                    # Kirim pesan konfirmasi sementara
                    confirmation_msg = await message.channel.send(f"Siap! ✨ Berhasil menghapus {delete_count} pesan terakhir.")
                    logger.info(f"User {message.author} ({message.author.id}) menghapus {delete_count} pesan di channel #{message.channel.name} ({message.guild.name})")

                    # Hapus pesan konfirmasi setelah beberapa detik (misal 5 detik)
                    await asyncio.sleep(5)
                    await confirmation_msg.delete()

                except discord.errors.Forbidden:
                    logger.warning(f"Gagal menghapus pesan di #{message.channel.name}: Bot tidak punya izin.")
                    await message.reply("Huhuu, aku nggak bisa hapus pesan di sini... Izinnya kurang kayaknya.")
                except discord.errors.HTTPException as e:
                    logger.error(f"Gagal menghapus pesan di #{message.channel.name}: {e}")
                    await message.reply(f"Aduhh, ada error pas mau bersih-bersih: {e}")
                except Exception as e:
                    logger.error(f"Error tak terduga saat proses clear: {e}")
                    await message.reply("Oops, error nggak jelas pas bersih-bersih... Maaf yaa T_T")

                # Akhiri pemrosesan di sini setelah clear command
                return

             # --- TAMBAHAN: Logika Membuat Emoji dari Gambar ---
            if is_emoji_command:
                # Cek izin bot (sama seperti stiker)
                if not message.guild.me.guild_permissions.manage_emojis_and_stickers:
                     await message.reply("Huhuu, aku nggak diizinin (`Manage Emojis and Stickers`) buat nambahin emoji di sini...")
                     return

                # Cek slot emoji (normal & animasi)
                emoji_limit = message.guild.emoji_limit
                animated_emoji_limit = message.guild.emoji_limit # batas sama? perlu konfirmasi ulang api discord, asumsikan sama
                normal_emojis = 0
                animated_emojis = 0
                for emoji in message.guild.emojis:
                     if emoji.animated:
                         animated_emojis += 1
                     else:
                         normal_emojis += 1

                # Cek attachment
                if not message.attachments:
                    await message.reply("Gambarnya mana yang mau dijadiin emoji? Lampirin dongg~")
                    return

                attachment = message.attachments[0]
                is_potentially_animated = attachment.content_type in ('image/gif')

                 # Cek slot berdasarkan jenis emoji
                if is_potentially_animated and animated_emojis >= animated_emoji_limit:
                     await message.reply(f"Waduh, slot buat emoji animasi di server ini udah penuh ({animated_emojis}/{animated_emoji_limit}). Nggak bisa nambah lagi T_T")
                     return
                elif not is_potentially_animated and normal_emojis >= emoji_limit:
                     await message.reply(f"Yahhh, slot buat emoji biasa di server ini udah penuh ({normal_emojis}/{emoji_limit}). Hapus beberapa dulu yuk?")
                     return

                # Periksa tipe konten attachment
                if not attachment.content_type or not attachment.content_type.startswith('image/'):
                    await message.reply("Itu kayaknya bukan gambar deh... Aku cuma bisa proses gambar (JPG, PNG, GIF).")
                    return

                # Ekstrak nama emoji dari perintah
                command_parts = message.content.split(maxsplit=1)
                if len(command_parts) < 2 or not command_parts[1].strip():
                     await message.reply("Nama emojinya apa? Kasih tau dong. Contoh: `!buatemoji namaKeren <lampirkan gambar>`")
                     return
                user_provided_name = command_parts[1].strip()
                emoji_name = clean_emoji_name(user_provided_name)

                await message.reply(f"Okeey, aku coba ya bikin emoji `:_{emoji_name}:` dari gambar `{attachment.filename}`...")

                try:
                    image_bytes = await attachment.read()
                    processed_image_buffer = await process_image_for_emoji(image_bytes) # Gunakan fungsi proses emoji

                    if processed_image_buffer:
                        # Upload sebagai emoji
                        new_emoji = await message.guild.create_custom_emoji(
                            name=emoji_name,
                            image=processed_image_buffer.read(), # Baca byte dari buffer
                            reason=f"Emoji dibuat atas permintaan {message.author}"
                        )
                        logger.info(f"Emoji ':{new_emoji.name}:' ({new_emoji.id}) berhasil dibuat di server {message.guild.name}")
                        await message.channel.send(f"Yeay! Emoji {new_emoji} (`:{new_emoji.name}:`) berhasil dibuat! Lucu kaaan? ✨")

                    else:
                        # Gagal memproses gambar (terlalu besar atau format salah setelah diproses)
                        await message.reply(f"Huhuu, gagal proses gambar `{attachment.filename}` T_T Pastiin formatnya JPG, PNG, atau GIF ya, dan ukurannya nggak lebih dari 256KB setelah diubah jadi {EMOJI_SIZE[0]}x{EMOJI_SIZE[1]}px.")

                except discord.errors.Forbidden:
                    logger.error(f"Gagal membuat emoji di {message.guild.name}: Izin ditolak.")
                    await message.reply("Gagal bikin emoji T_T Kayaknya aku nggak punya izin...")
                except discord.errors.HTTPException as e:
                    logger.error(f"Gagal membuat emoji di {message.guild.name}: {e}")
                    error_msg = str(e).lower()
                    if 'maximum number of emojis reached' in error_msg:
                         await message.reply("Yahh, slot emoji di server ini udah penuh ternyata...")
                    elif 'invalid image data' in error_msg or 'invalid form body' in error_msg:
                        await message.reply("Ada masalah sama data gambarnya nih setelah diproses. Coba gambar lain?")
                    elif 'emoji name is already taken' in error_msg:
                         await message.reply(f"Nama `:{emoji_name}:` udah ada yang punyaa. Coba ganti nama lain yaa.")
                    elif 'string value is too short' in error_msg or 'string value is too long' in error_msg:
                         await message.reply(f"Nama `:{emoji_name}:` terlalu pendek atau panjang ({len(emoji_name)} char). Harus antara 2-32 karakter alfanumerik/underscore.")
                    else:
                         await message.reply(f"Aduuh, ada error pas upload emoji: {e}")
                except Exception as e:
                     logger.exception(f"Error tak terduga saat proses emoji dari gambar: {e}") # Pakai exception untuk traceback
                     await message.reply("Aaa, error ga jelas pas bikin emoji dari gambar... Maaf yaa T_T")

            # --- Logika Membuat Stiker dari Gambar (Kode Asli Dimodifikasi Sedikit) ---
            elif is_image_sticker_command:
                if not message.guild.me.guild_permissions.manage_emojis_and_stickers:
                     await message.reply("Maaf, saya tidak punya izin `Manage Emojis and Stickers` di server ini.")
                     return

                if not message.attachments:
                    await message.reply("Harap lampirkan gambar yang ingin dijadikan stiker bersama perintah ini.")
                    return

                attachment = message.attachments[0]
                if not attachment.content_type or not attachment.content_type.startswith('image/'):
                    await message.reply("File yang dilampirkan sepertinya bukan gambar.")
                    return

                try:
                     current_stickers = await message.guild.fetch_stickers()
                     if len(current_stickers) >= message.guild.sticker_limit:
                         await message.reply("Maaf, slot stiker di server ini sudah penuh.")
                         return
                except discord.HTTPException as e:
                    logger.error(f"Gagal mengambil daftar stiker: {e}")
                    await message.reply("Tidak bisa memeriksa slot stiker saat ini.")
                    return

                command_parts = message.content.split(maxsplit=1)
                user_provided_name = command_parts[1].strip() if len(command_parts) > 1 else attachment.filename
                sticker_name = clean_sticker_name(user_provided_name)
                sticker_emoji = "🖼️"

                await message.reply(f"Memproses gambar `{attachment.filename}` untuk dijadikan stiker bernama `{sticker_name}`...")

                try:
                    image_bytes = await attachment.read()
                    processed_image_buffer = await process_image_for_sticker(image_bytes)

                    if processed_image_buffer:
                        sticker_file = discord.File(processed_image_buffer, filename=f"{sticker_name}.png")
                        new_sticker = await message.guild.create_sticker(
                            name=sticker_name,
                            description=f"Stiker dari gambar {attachment.filename} oleh {message.author.display_name}",
                            emoji=sticker_emoji,
                            file=sticker_file,
                            reason=f"Dibuat atas permintaan {message.author}"
                        )
                        logger.info(f"Stiker gambar '{new_sticker.name}' berhasil dibuat di server {message.guild.name}")
                        await message.channel.send(f"Stiker `{new_sticker.name}` berhasil dibuat dari gambar!", stickers=[new_sticker])
                    else:
                        await message.reply(f"Tidak bisa memproses gambar `{attachment.filename}`. Pastikan formatnya didukung (JPG, PNG, GIF) dan ukurannya tidak terlalu besar setelah diubah menjadi {STICKER_SIZE[0]}x{STICKER_SIZE[1]} (maks 512KB).")

                except discord.errors.Forbidden:
                    logger.error(f"Gagal membuat stiker gambar di {message.guild.name}: Izin ditolak.")
                    await message.reply("Gagal membuat stiker. Pastikan saya punya izin yang benar.")
                except discord.errors.HTTPException as e:
                    logger.error(f"Gagal membuat stiker gambar di {message.guild.name}: {e}")
                    error_msg = str(e).lower()
                    if 'maximum number of stickers reached' in error_msg:
                         await message.reply("Maaf, slot stiker di server ini sudah penuh.")
                    elif 'invalid asset' in error_msg or 'invalid form body' in error_msg:
                        await message.reply("Terjadi masalah dengan data gambar setelah diproses. Coba gambar lain.")
                    else:
                         await message.reply(f"Terjadi kesalahan HTTP saat mengupload stiker: {e}")
                except Exception as e:
                     logger.exception(f"Error tak terduga saat proses stiker gambar: {e}")
                     await message.reply("Maaf, terjadi error tak terduga saat memproses stiker dari gambar.")

            # --- Logika Membuat Stiker dari Teks (Kode Asli Dimodifikasi Sedikit) ---
            elif is_text_sticker_command:
                if not message.guild.me.guild_permissions.manage_emojis_and_stickers:
                     await message.reply("Maaf, saya tidak punya izin `Manage Emojis and Stickers` untuk membuat stiker di server ini.")
                     return

                try:
                     current_stickers = await message.guild.fetch_stickers()
                     if len(current_stickers) >= message.guild.sticker_limit:
                         await message.reply("Maaf, slot stiker di server ini sudah penuh.")
                         return
                except discord.HTTPException as e:
                    logger.error(f"Gagal mengambil daftar stiker: {e}")
                    await message.reply("Tidak bisa memeriksa slot stiker saat ini.")
                    return

                sticker_text_raw = message.content[len("buatkan stiker:"):].strip()
                if not sticker_text_raw:
                    await message.reply("Harap berikan teks untuk stikernya! Contoh: `buatkan stiker: Halo Dunia`")
                    return

                sticker_text = sticker_text_raw[:30]
                if len(sticker_text_raw) > 30:
                    await message.channel.send(f"Teks stiker terlalu panjang, dipotong menjadi: `{sticker_text}`")

                sticker_name = clean_sticker_name(sticker_text)
                related_emoji = "✨"

                await message.reply(f"Sedang mencoba membuat stiker teks: `{sticker_text}`...")

                sticker_image_bytes = await create_text_sticker_image(sticker_text)

                if sticker_image_bytes:
                    try:
                        sticker_file = discord.File(sticker_image_bytes, filename=f"{sticker_name}.png")
                        new_sticker = await message.guild.create_sticker(
                            name=sticker_name,
                            description=f"Stiker teks dibuat oleh bot: {sticker_text}",
                            emoji=related_emoji,
                            file=sticker_file,
                            reason=f"Dibuat atas permintaan {message.author}"
                        )
                        logger.info(f"Stiker teks '{new_sticker.name}' berhasil dibuat di server {message.guild.name}")
                        await message.channel.send(f"Stiker `{new_sticker.name}` berhasil dibuat!", stickers=[new_sticker])

                    except discord.errors.Forbidden:
                        logger.error(f"Gagal membuat stiker teks di {message.guild.name}: Izin ditolak.")
                        await message.reply("Gagal membuat stiker. Pastikan saya punya izin yang benar.")
                    except discord.errors.HTTPException as e:
                        logger.error(f"Gagal membuat stiker teks di {message.guild.name}: {e}")
                        error_msg = str(e).lower()
                        if 'maximum number of stickers reached' in error_msg:
                             await message.reply("Maaf, slot stiker di server ini sudah penuh.")
                        elif 'empty image' in error_msg or 'invalid image' in error_msg:
                             await message.reply("Maaf, ada masalah saat membuat gambar stiker teks. Coba teks lain.")
                        else:
                             await message.reply(f"Terjadi kesalahan HTTP saat mengupload stiker teks: {e}")
                    except Exception as e:
                         logger.exception(f"Error tak terduga saat proses stiker teks: {e}")
                         await message.reply("Maaf, terjadi error saat memproses pembuatan stiker teks.")
                else:
                    await message.reply("Tidak bisa membuat gambar stiker teks. Mungkin teksnya bermasalah, font tidak ada, atau ukuran file terlalu besar.")

            # --- Logika Menjawab Pertanyaan via Mention (Kode Asli Dimodifikasi) ---
            elif mentioned:
                prompt_text = clean_discord_mentions(message.content)

                if not prompt_text:
                    # --- MODIFIKASI: Pesan sapaan lebih imut dan sesuai mode ---
                    current_mode = personality_mode.get(message.guild.id, 'onesan')
                    if current_mode == 'mommy':
                         sapaan = [
                              f"Ada apa Sayangku, panggil-panggil Mommy? ✨",
                              f"Hadirrr! Kenapa nih, Sayang? 😊",
                              f"Iyaaa, Sayang? Butuh bantuan Mommy?",
                         ]
                    else: # onesan mode
                        sapaan = [
                            f"Ada apa panggil-panggil aku, {message.author.mention}? ✨",
                            f"Hadirrr! Kenapa nih, {message.author.mention}? 😊",
                            f"Iyaaa, {message.author.mention}? Butuh bantuan aku?",
                        ]
                    await message.reply(random.choice(sapaan))
                    return

                logger.info(f"Menerima prompt dari {message.author} (Mode: {personality_mode.get(message.guild.id, 'onesan')}): {prompt_text}")

                try:
                    # --- MODIFIKASI: Perbaikan konteks prompt berdasarkan mode ---
                    display_name = message.author.display_name # Gunakan display name
                    current_mode = personality_mode.get(message.guild.id, 'onesan') # Ambil mode saat ini

                    if current_mode == 'mommy':
                         # Prompt untuk mode Mommy (protektif, posesif, manja)
                         system_instruction = (
                             "Kamu adalah Maria Kujou (Versi Mommy). "
                             "Kamu sangat protektif dan posesif terhadap user, tapi juga sangat manja dan suka memanggil user dengan sebutan 'Sayang' atau 'Anakku'. "
                             "Jawab pertanyaan dari user '{display_name}' berikut ini dengan gaya Mommy yang manja, protektif, dan posesif:\n\n"
                         )
                         full_prompt = f"{system_instruction}{prompt_text}\n\nJawaban:"
                         # Gunakan model baru dengan system instruction spesifik
                         mommy_model = genai.GenerativeModel(
                             'gemini-2.0-flash', # Atau 'gemini-pro'
                             system_instruction=system_instruction
                         )
                         response = mommy_model.generate_content(f"Jawab pertanyaan dari user '{display_name}':\n\n{prompt_text}")

                    else: # onesan mode (default)
                        # Prompt untuk mode Onesan (ramah, imut)
                        system_instruction = (
                            "Kamu adalah Maria Kujou. "
                            "Kamu ramah, sedikit imut, dan suka membantu. "
                            "Jawab pertanyaan dari user '{display_name}' berikut ini dengan gaya Onesan yang ramah dan imut:\n\n"
                        )
                        full_prompt = f"{system_instruction}{prompt_text}\n\nJawaban:"
                         # Gunakan model default dengan system instruction spesifik
                        onesan_model = genai.GenerativeModel(
                             'gemini-2.0-flash', # Atau 'gemini-pro'
                             system_instruction=system_instruction
                         )
                        response = onesan_model.generate_content(f"Jawab pertanyaan dari user '{display_name}':\n\n{prompt_text}")


                    ai_response_text = response.text

                    if len(ai_response_text) > 1950:
                        ai_response_text = ai_response_text[:1950] + "... (huhu kepanjangan T_T)"

                    # --- MODIFIKASI: Emoji lebih variatif/imut/sesuai mode ---
                    if current_mode == 'mommy':
                         emojis = ["❤️", "😘", "🥺", "🥰", "🔒", "ぎゅっ (Gyu!)"] # Emoji Mommy
                    else: # onesan mode
                         emojis = ["😊", "✨", "💡", "💖", "🌸", "🎀", "✅", "😉", "ヽ(*⌒∇⌒*)ﾉ"] # Emoji Onesan

                    response_with_emoji = f"{ai_response_text} {random.choice(emojis)}"

                    await message.reply(response_with_emoji)
                    logger.info(f"Mengirim balasan AI ke {message.author} (Mode: {current_mode})")

                except Exception as e:
                    logger.error(f"Error saat memanggil Google AI atau mengirim pesan: {e}")
                    # --- MODIFIKASI: Pesan error lebih imut ---
                    error_emojis = ["😟", "❌", "😥", "🤯", " T_T", " ಥ_ಥ"]
                    await message.reply(f"Aduuuh {message.author.mention}, maaf banget... Kayaknya otak AI-ku lagi korslet nih. Coba tanya lagi nanti yaaa... {random.choice(error_emojis)}")

# --- Jalankan Bot ---
try:
    client.run(DISCORD_TOKEN)
except discord.errors.LoginFailure:
    logger.error("Gagal login ke Discord. Pastikan DISCORD_TOKEN di .env sudah benar.")
except discord.errors.PrivilegedIntentsRequired as e:
     logger.error(f"Gagal konek karena Intent tertentu belum diaktifkan: {e}. Pastikan 'SERVER MEMBERS INTENT' dan 'MESSAGE CONTENT INTENT' aktif di Discord Developer Portal.")
     print("\n!!! PENTING: Anda perlu mengaktifkan 'Privileged Gateway Intents' (SERVER MEMBERS INTENT & MESSAGE CONTENT INTENT) di pengaturan bot Anda di Discord Developer Portal (https://discord.com/developers/applications) !!!\n")
     # Tambahkan juga cek untuk `moderation` jika error spesifik muncul
     if 'moderation' in str(e):
          print("!!! Fitur Timeout memerlukan izin 'Moderate Members' dan mungkin Intent 'Moderation' juga perlu dicek. !!!\n")
except Exception as e:
    logger.error(f"Error kritis saat menjalankan bot: {e}")
import discord
import os
import google.generativeai as genai
from dotenv import load_dotenv
import random
from PIL import Image, ImageDraw, ImageFont
import io
import logging
import re # Import regex

# Konfigurasi logging dasar
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')

# Muat variabel environment dari file .env
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Validasi Kunci API ---
if not DISCORD_TOKEN:
    logger.error("Error: DISCORD_TOKEN tidak ditemukan di file .env")
    exit()
if not GOOGLE_API_KEY:
    logger.error("Error: GOOGLE_API_KEY tidak ditemukan di file .env")
    exit()

# --- Konfigurasi Google Generative AI ---
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    # Pilih model Gemini yang sesuai (misal: gemini-1.5-flash atau gemini-pro)
    model = genai.GenerativeModel(
        'gemini-2.0-flash', # Atau 'gemini-pro'
        system_instruction="Kamu adalah Alya yaitu gadis yang sangat lembut, penyayang, manja, dan juga rajin. kamu juga sangat tsundere jika ada yang memanjakanmu, kamu sangat pintar dan sopan tapi juga gaul. kamu bisa berbicara bahasa indonesia dan juga jepang tapi dalam bentuk latin, walaupun kamu sangat tsundere tapi kamu sangat peduli dan penyayang kepada orang dekatmu."
    )
    logger.info("Google Generative AI berhasil dikonfigurasi.")
except Exception as e:
    logger.error(f"Error konfigurasi Google Generative AI: {e}")
    exit()

# --- Konfigurasi Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True # Perlu untuk membaca isi pesan
intents.guilds = True          # Perlu untuk info server (misal: membuat stiker)

# Menggunakan Bot class untuk command handling yang lebih mudah di masa depan,
# tapi untuk contoh ini Client sudah cukup. Kita tetap pakai Client sesuai permintaan awal.
client = discord.Client(intents=intents)

# --- Pengaturan Stiker ---
STICKER_SIZE = (320, 320)  # Ukuran stiker Discord (harus persegi, maks 512KB)
# Coba cari font. Ganti 'Poppins-Regular.ttf' dengan nama file font Anda.
# Jika tidak ada, gunakan font default Pillow (mungkin tidak ideal).
FONT_PATH = 'Poppins-Regular.ttf' # Ganti jika perlu
DEFAULT_FONT_SIZE = 40
try:
    font = ImageFont.truetype(FONT_PATH, DEFAULT_FONT_SIZE)
    logger.info(f"Font '{FONT_PATH}' berhasil dimuat.")
except IOError:
    logger.warning(f"Font '{FONT_PATH}' tidak ditemukan. Menggunakan font default Pillow.")
    try:
        font = ImageFont.load_default(size=DEFAULT_FONT_SIZE) # Mencoba memuat font default dengan ukuran spesifik
    except AttributeError: # Handle jika load_default tidak menerima size (versi Pillow lama)
         font = ImageFont.load_default()
         logger.warning(f"Memuat font default Pillow tanpa ukuran spesifik.")


# --- Fungsi Bantuan ---
def clean_discord_mentions(text):
    """Menghapus mention user dan role dari teks."""
    text = re.sub(r'<@!?\d+>', '', text) # Hapus mention user (<@USER_ID> atau <@!USER_ID>)
    text = re.sub(r'<@&\d+>', '', text)  # Hapus mention role (<@&ROLE_ID>)
    return text.strip()

async def create_sticker_image(text):
    """Membuat gambar stiker dari teks menggunakan Pillow."""
    image = Image.new('RGBA', STICKER_SIZE, (255, 255, 255, 0)) # Latar belakang transparan
    draw = ImageDraw.Draw(image)

    # Sesuaikan ukuran font agar teks pas
    current_font = font
    text_width, text_height = draw.textbbox((0,0), text, font=current_font)[2:4] # Dapatkan bounding box
    max_width = STICKER_SIZE[0] - 20 # Beri sedikit padding

    # Kecilkan font jika teks terlalu lebar
    while text_width > max_width and current_font.size > 10:
        new_size = current_font.size - 2
        try:
             current_font = ImageFont.truetype(FONT_PATH, new_size)
        except IOError:
             try:
                 current_font = ImageFont.load_default(size=new_size)
             except AttributeError:
                 current_font = ImageFont.load_default() # Fallback paling dasar
                 if current_font.size <= 10: break # Hindari infinite loop jika font default sangat kecil

        text_width, text_height = draw.textbbox((0,0), text, font=current_font)[2:4]

    # Hitung posisi teks agar di tengah
    x = (STICKER_SIZE[0] - text_width) / 2
    y = (STICKER_SIZE[1] - text_height) / 2

    # Gambar teks dengan outline sederhana (opsional)
    outline_color="black"
    text_color="white"
    # draw.text((x-1, y-1), text, font=current_font, fill=outline_color)
    # draw.text((x+1, y-1), text, font=current_font, fill=outline_color)
    # draw.text((x-1, y+1), text, font=current_font, fill=outline_color)
    # draw.text((x+1, y+1), text, font=current_font, fill=outline_color)
    draw.text((x, y), text, font=current_font, fill=text_color, stroke_width=1, stroke_fill=outline_color) # Stroke lebih baik

    # Simpan gambar ke buffer byte
    img_byte_arr = io.BytesIO()
    try:
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        # Pastikan ukuran file tidak melebihi batas Discord (512KB)
        if img_byte_arr.getbuffer().nbytes > 512 * 1024:
            logger.warning("Ukuran file stiker melebihi 512KB setelah dibuat.")
            # Di sini bisa ditambahkan logika kompresi atau pemberitahuan error
            return None # Kembalikan None jika terlalu besar
        return img_byte_arr
    except Exception as e:
        logger.error(f"Gagal menyimpan gambar stiker ke buffer: {e}")
        return None


# --- Event Listener ---
@client.event
async def on_ready():
    """Dipanggil saat bot berhasil terhubung ke Discord."""
    logger.info(f'Bot {client.user} telah terhubung ke Discord!')
    logger.info('Siap menerima perintah.')
    # Set status bot (opsional)
    await client.change_presence(activity=discord.Game(name=f"Mention saya!"))

@client.event
async def on_message(message):
    """Dipanggil setiap kali ada pesan baru di channel yang bisa diakses bot."""
    # 1. Abaikan pesan dari bot itu sendiri
    if message.author == client.user:
        return

    # 2. Periksa apakah bot di-mention atau pesan dimulai dengan keyword stiker
    mentioned = client.user.mentioned_in(message)
    is_sticker_command = message.content.lower().startswith("buatkan stiker:")

    if mentioned or is_sticker_command:
        # Tampilkan indikator mengetik
        async with message.channel.typing():
            # --- Logika Membuat Stiker ---
            if is_sticker_command:
                # Pastikan perintah dijalankan di server (guild), bukan DM
                if not message.guild:
                    await message.reply("Maaf, perintah stiker hanya bisa digunakan di dalam server.")
                    return

                # Cek izin bot untuk mengelola stiker
                if not message.guild.me.guild_permissions.manage_emojis_and_stickers:
                     await message.reply("Maaf, saya tidak punya izin `Manage Emojis and Stickers` untuk membuat stiker di server ini.")
                     return

                # Cek slot stiker yang tersedia
                if len(await message.guild.fetch_stickers()) >= message.guild.sticker_limit:
                    await message.reply("Maaf, slot stiker di server ini sudah penuh.")
                    return

                sticker_text_raw = message.content[len("buatkan stiker:"):].strip()
                if not sticker_text_raw:
                    await message.reply("Harap berikan teks untuk stikernya! Contoh: `buatkan stiker: Halo Dunia`")
                    return

                # Batasi panjang teks stiker (misalnya maks 30 karakter)
                sticker_text = sticker_text_raw[:30]
                if len(sticker_text_raw) > 30:
                    await message.channel.send(f"Teks stiker terlalu panjang, dipotong menjadi: `{sticker_text}`")


                # Buat nama stiker yang valid (alfanumerik, underscore, min 2 char)
                sticker_name = re.sub(r'\W+', '_', sticker_text) # Ganti non-alphanum dengan _
                sticker_name = re.sub(r'_+', '_', sticker_name).strip('_') # Hapus underscore berlebih
                if len(sticker_name) < 2:
                    sticker_name = f"stiker_{random.randint(100,999)}" # Fallback name
                sticker_name = sticker_name[:30] # Batasi panjang nama

                # Pilih emoji terkait (bisa minta AI atau pakai yang simpel)
                related_emoji = "✨" # Default emoji

                await message.reply(f"Sedang mencoba membuat stiker dengan teks: `{sticker_text}`...")

                sticker_image_bytes = await create_sticker_image(sticker_text)

                if sticker_image_bytes:
                    try:
                        # Buat file Discord dari buffer byte
                        sticker_file = discord.File(sticker_image_bytes, filename=f"{sticker_name}.png")
                        # Upload stiker ke server
                        new_sticker = await message.guild.create_sticker(
                            name=sticker_name,
                            description=f"Stiker dibuat oleh bot: {sticker_text}",
                            emoji=related_emoji,
                            file=sticker_file,
                            reason=f"Dibuat atas permintaan {message.author}"
                        )
                        logger.info(f"Stiker '{new_sticker.name}' berhasil dibuat di server {message.guild.name}")
                        # Kirim stiker yang baru dibuat sebagai konfirmasi
                        await message.channel.send(f"Stiker `{new_sticker.name}` berhasil dibuat!", stickers=[new_sticker])

                    except discord.errors.Forbidden:
                        logger.error(f"Gagal membuat stiker di {message.guild.name}: Izin ditolak.")
                        await message.reply("Gagal membuat stiker. Pastikan saya punya izin yang benar.")
                    except discord.errors.HTTPException as e:
                        logger.error(f"Gagal membuat stiker di {message.guild.name}: {e}")
                        if 'Maximum number of stickers reached' in str(e):
                             await message.reply("Maaf, slot stiker di server ini sudah penuh.")
                        elif 'empty image' in str(e).lower() or 'invalid image' in str(e).lower():
                             await message.reply("Maaf, ada masalah saat membuat gambar stiker. Coba teks lain.")
                        else:
                             await message.reply(f"Terjadi kesalahan saat mengupload stiker: {e}")
                    except Exception as e: # Tangkap error Pillow atau lainnya
                         logger.error(f"Error tak terduga saat proses stiker: {e}")
                         await message.reply("Maaf, terjadi error saat memproses pembuatan stiker.")
                else:
                    # Gagal membuat gambar (misal, terlalu besar atau error Pillow)
                    await message.reply("Tidak bisa membuat gambar stiker. Mungkin teksnya bermasalah atau ukuran file terlalu besar.")

            # --- Logika Menjawab Pertanyaan via Mention ---
            elif mentioned:
                # Hapus mention bot dari pesan untuk mendapatkan prompt asli
                prompt_text = clean_discord_mentions(message.content)

                if not prompt_text: # Jika hanya mention tanpa teks lain
                    await message.reply(f"Halo {message.author.mention}! Ada yang bisa saya bantu? ✨")
                    return

                logger.info(f"Menerima prompt dari {message.author}: {prompt_text}")

                try:
                    # Kirim prompt ke model AI Generatif
                    # Menambahkan sedikit konteks agar AI tahu dia adalah bot Discord
                    full_prompt = f"Kamu adalah bot Discord yang ramah dan membantu. Jawab pertanyaan berikut dari user '{message.author.display_name}':\n\n{prompt_text}"

                    response = model.generate_content(full_prompt)
                    ai_response_text = response.text

                    # Tambahkan emoji acak ke respons (opsional)
                    emojis = ["😊", "✨", "💡", "🤖", "👍", "🤔", "✅"]
                    response_with_emoji = f"{ai_response_text} {random.choice(emojis)}"

                    # Kirim balasan (gunakan reply untuk mengutip pesan asli)
                    await message.reply(response_with_emoji)
                    logger.info(f"Mengirim balasan AI ke {message.author}")

                except Exception as e:
                    logger.error(f"Error saat memanggil Google AI atau mengirim pesan: {e}")
                    # Beri tahu user jika ada masalah
                    error_emojis = ["😟", "❌", "😥"]
                    await message.reply(f"Maaf, terjadi sedikit masalah saat memproses permintaanmu. {random.choice(error_emojis)}")

# --- Jalankan Bot ---
try:
    client.run(DISCORD_TOKEN)
except discord.errors.LoginFailure:
    logger.error("Gagal login ke Discord. Pastikan DISCORD_TOKEN di .env sudah benar.")
except Exception as e:
    logger.error(f"Error saat menjalankan bot: {e}")
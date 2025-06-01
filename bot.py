import os
import aiohttp
import threading
import time
import requests
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from threading import Thread
import sqlite3

# 🔐 Token aus .env laden
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN konnte nicht aus der .env geladen werden!")

# 📡 Bot konfigurieren
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DB_FILE = "gear_data.db"
synced_once = False

# --- SQLite Setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS gear (
            user_id INTEGER PRIMARY KEY,
            familyname TEXT,
            class TEXT,
            state TEXT,
            ap INTEGER,
            aap INTEGER,
            dp INTEGER,
            gearscore REAL,
            proof TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 📥 Anhang speichern
async def download_and_save_attachment(attachment: discord.Attachment, user_id: int):
    folder = "proofs"
    os.makedirs(folder, exist_ok=True)
    filename = f"{user_id}_{attachment.filename}"
    filepath = os.path.join(folder, filename)

    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as resp:
            if resp.status == 200:
                with open(filepath, "wb") as f:
                    f.write(await resp.read())
                return filepath
    return None

# 💾 Gear speichern/laden mit SQLite
def save_gear(user_id, gear_data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO gear (user_id, familyname, class, state, ap, aap, dp, gearscore, proof)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            familyname=excluded.familyname,
            class=excluded.class,
            state=excluded.state,
            ap=excluded.ap,
            aap=excluded.aap,
            dp=excluded.dp,
            gearscore=excluded.gearscore,
            proof=excluded.proof
    ''', (
        user_id,
        gear_data.get("familyname"),
        gear_data.get("class"),
        gear_data.get("state"),
        gear_data.get("ap"),
        gear_data.get("aap"),
        gear_data.get("dp"),
        gear_data.get("gearscore"),
        gear_data.get("proof")
    ))
    conn.commit()
    conn.close()

def load_gear(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT familyname, class, state, ap, aap, dp, gearscore, proof FROM gear WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "familyname": row[0],
            "class": row[1],
            "state": row[2],
            "ap": row[3],
            "aap": row[4],
            "dp": row[5],
            "gearscore": row[6],
            "proof": row[7]
        }
    return None

def load_all_gears():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT user_id, familyname, class, state, ap, aap, dp, gearscore, proof FROM gear')
    rows = c.fetchall()
    conn.close()

    all_gears = {}
    for row in rows:
        user_id = row[0]
        all_gears[user_id] = {
            "familyname": row[1],
            "class": row[2],
            "state": row[3],
            "ap": row[4],
            "aap": row[5],
            "dp": row[6],
            "gearscore": row[7],
            "proof": row[8]
        }
    return all_gears

async def safe_send(interaction, *args, **kwargs):
    try:
        await interaction.response.send_message(*args, **kwargs)
    except:
        pass

# 🚀 Bot ready
@bot.event
async def on_ready():
    global synced_once
    print(f"✅ Bot ist online als {bot.user}")
    if not synced_once:
        try:
            synced = await bot.tree.sync()
            synced_once = True
            print(f"✅ {len(synced)} Slash Commands synchronisiert.")
        except Exception as e:
            print(f"❌ Fehler beim Slash Sync: {e}")

# 🛠️ Slash Commands
@bot.tree.command(name="gear_set", description="Setze dein Gear inkl. optionalem Bild")
@app_commands.describe(
    familyname="Optional: Dein Familyname",
    klasse="Gib deine Klasse ein",
    state="Awakening oder Succession",
    ap="Attack Power",
    aap="Awakening AP",
    dp="Defense Power",
    proof="Optional: Bildbeweis"
)
async def gear_set(interaction: discord.Interaction, klasse: str, state: str, ap: int, aap: int, dp: int,
                   familyname: str = None, proof: discord.Attachment = None):
    if state.lower() not in ['awakening', 'succession']:
        await safe_send(interaction, "❌ Ungültiger State! Nur 'Awakening' oder 'Succession' erlaubt.")
        return

    gearscore = (ap + aap) / 2 + dp
    gear_data = {
        "familyname": familyname,
        "class": klasse,
        "state": state,
        "ap": ap,
        "aap": aap,
        "dp": dp,
        "gearscore": round(gearscore, 2),
        "proof": None
    }

    if proof:
        filepath = await download_and_save_attachment(proof, interaction.user.id)
        if filepath:
            gear_data["proof"] = filepath

    save_gear(interaction.user.id, gear_data)
    await safe_send(interaction, f"✅ Gear gespeichert! Gearscore: **{round(gearscore, 2)}**")

@bot.tree.command(name="gear_show", description="Zeigt dein Gear oder das eines anderen")
@app_commands.describe(user="Optional: anderer User")
async def gear_show(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    data = load_gear(target.id)
    if not data:
        await safe_send(interaction, "❌ Kein Gear gefunden.")
        return

    embed = discord.Embed(title=f"Gear von {target.display_name}", color=0x00ffcc)
    embed.add_field(name="Familyname", value=data.get("familyname", "❓"), inline=True)
    embed.add_field(name="Klasse", value=data.get("class", "❓"), inline=True)
    embed.add_field(name="State", value=data.get("state", "❓"), inline=True)
    embed.add_field(name="AP / AAP", value=f"{data.get('ap')} / {data.get('aap')}", inline=True)
    embed.add_field(name="DP", value=str(data.get("dp")), inline=True)
    embed.add_field(name="Gearscore", value=str(data.get("gearscore")), inline=True)

    if data.get("proof") and os.path.exists(data["proof"]):
        file = discord.File(data["proof"], filename="proof.png")
        embed.set_image(url="attachment://proof.png")
        await safe_send(interaction, embed=embed, file=file)
    else:
        await safe_send(interaction, embed=embed)

@bot.tree.command(name="gear_list", description="Zeigt alle Geardaten nach Gearscore")
async def gear_list(interaction: discord.Interaction):
    all_gears = load_all_gears()
    if not all_gears:
        await safe_send(interaction, "❌ Keine Geardaten vorhanden.")
        return

    sorted_gears = sorted(all_gears.items(), key=lambda x: x[1]["gearscore"], reverse=True)
    embed = discord.Embed(title="📊 Gear Liste (nach Gearscore sortiert)", color=0x00ffcc)

    for i, (user_id, data) in enumerate(sorted_gears, start=1):
        prefix = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        embed.add_field(
            name=f"{prefix} {data.get('familyname', '❓')} - {data.get('class', '❓')}",
            value=(
                f"**Gearscore:** {data.get('gearscore', '?')}\n"
                f"State: {data.get('state', '❓')}\n"
                f"AP: {data.get('ap', '?')} | AAP: {data.get('aap', '?')} | DP: {data.get('dp', '?')}\n"
                f"〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️"
            ),
            inline=False
        )
    await safe_send(interaction, embed=embed)

@bot.tree.command(name="gear_update", description="Aktualisiere dein gespeichertes Gear")
@app_commands.describe(
    familyname="Optional: Neuer Familyname",
    klasse="Optional: Neue Klasse",
    state="Optional: Neuer State ('Awakening' oder 'Succession')",
    ap="Optional: Neuer AP-Wert",
    aap="Optional: Neuer AAP-Wert",
    dp="Optional: Neuer DP-Wert",
    proof="Optional: Neues Bild"
)
async def gear_update(
    interaction: discord.Interaction,
    familyname: str = None,
    klasse: str = None,
    state: str = None,
    ap: int = None,
    aap: int = None,
    dp: int = None,
    proof: discord.Attachment = None
):
    data = load_gear(interaction.user.id)
    if not data:
        await safe_send(interaction, "❌ Du hast noch kein Gear gespeichert. Nutze zuerst `/gear_set`.")
        return

    if state and state.lower() not in ['awakening', 'succession']:
        await safe_send(interaction, "❌ Ungültiger State! Nur 'Awakening' oder 'Succession' erlaubt.")
        return

    if familyname: data['familyname'] = familyname
    if klasse: data['class'] = klasse
    if state: data['state'] = state
    if ap is not None: data['ap'] = ap
    if aap is not None: data['aap'] = aap
    if dp is not None: data['dp'] = dp

    if proof:
        filepath = await download_and_save_attachment(proof, interaction.user.id)
        if filepath:
            data['proof'] = filepath

    data['gearscore'] = round((data['ap'] + data['aap']) / 2 + data['dp'], 2)
    save_gear(interaction.user.id, data)

    await safe_send(interaction, f"✅ Gear aktualisiert! Neuer Gearscore: **{data['gearscore']}**")

# 🌐 Flask-Webserver für Replit
app = Flask('')

@app.route('/')
def home():
    return "Bot läuft!"

def run():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# 🔁 Self-Ping an Replit-URL
def self_ping():
    while True:
        try:
            url = "https://gearbot.danieldyllong.repl.co"  # Bitte ggf. URL anpassen!
            r = requests.get(url)
            print(f"🔁 Self-ping: {r.status_code}")
        except Exception as e:
            print(f"⚠️ Self-ping Fehler: {e}")
        time.sleep(280)

threading.Thread(target=self_ping).start()

# Bot starten
bot.run(TOKEN)

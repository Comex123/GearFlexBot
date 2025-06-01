import os
import json
import subprocess
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from dotenv import load_dotenv
from flask import Flask
import threading

# ==== Flask Dummy Server für Render ====
app = Flask(__name__)

@app.route('/')
def index():
    return "✅ Bot läuft!"

def run_web():
    port = int(os.environ.get("PORT", 8080))  # Render erwartet offenen Port
    app.run(host='0.0.0.0', port=port)

# ==== Token & GitHub Config laden ====
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # z.B. "username/repo"

if not TOKEN or not GITHUB_USERNAME or not GITHUB_TOKEN or not GITHUB_REPO:
    raise ValueError("Bitte DISCORD_TOKEN, GITHUB_USERNAME, GITHUB_TOKEN und GITHUB_REPO in .env setzen!")

# ==== Bot Setup ====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "gear_data.json"
gear_data = {}

# Lade bestehende Daten
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        gear_data = json.load(f)

# Git Commit & Push Funktion
def git_commit_and_push(commit_msg="Update gear data"):
    try:
        subprocess.run(["git", "add", DATA_FILE], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        repo_url = f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        subprocess.run(["git", "push", repo_url, "main"], check=True)
        print("✅ Git push erfolgreich")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git Fehler: {e}")

# Speichern
def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(gear_data, f, indent=4, ensure_ascii=False)
    git_commit_and_push("Automatischer Update der Gear Daten")

def load_gear(user_id):
    return gear_data.get(str(user_id))

def save_gear(user_id, data):
    gear_data[str(user_id)] = data
    save_data()

async def download_and_save_attachment(attachment: discord.Attachment, user_id: int):
    folder = "proofs"
    os.makedirs(folder, exist_ok=True)
    filename = f"{user_id}_{attachment.filename}"
    filepath = os.path.join(folder, filename)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status == 200:
                    with open(filepath, "wb") as f:
                        f.write(await resp.read())
                    return filepath
    except Exception as e:
        print(f"❌ Fehler beim Download: {e}")
    return None

async def safe_send(interaction, *args, **kwargs):
    try:
        await interaction.response.send_message(*args, **kwargs)
    except discord.InteractionResponded:
        try:
            await interaction.followup.send(*args, **kwargs)
        except Exception as e:
            print(f"⚠️ Fehler beim Senden der Followup-Nachricht: {e}")
    except Exception as e:
        print(f"⚠️ Fehler beim Senden der Nachricht: {e}")

@bot.event
async def on_ready():
    print(f"✅ Bot ist online als {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Slash Commands synchronisiert.")
    except Exception as e:
        print(f"❌ Fehler beim Slash Sync: {e}")

@bot.tree.command(name="gear_set", description="Setze dein Gear inkl. optionalem Bild")
@app_commands.describe(
    familyname="Optional: Dein Familyname",
    klasse="Deine Klasse",
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
    data = {
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
            data["proof"] = filepath

    save_gear(interaction.user.id, data)
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
    if not gear_data:
        await safe_send(interaction, "❌ Keine Geardaten vorhanden.")
        return

    sorted_gears = sorted(gear_data.items(), key=lambda x: x[1]["gearscore"], reverse=True)
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
async def gear_update(interaction: discord.Interaction, familyname: str = None, klasse: str = None, state: str = None,
                      ap: int = None, aap: int = None, dp: int = None, proof: discord.Attachment = None):
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

# ==== Webserver starten (Render benötigt offenen Port!) ====
threading.Thread(target=run_web).start()

# ==== Bot starten ====
bot.run(TOKEN)

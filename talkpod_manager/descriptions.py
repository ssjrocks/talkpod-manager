"""Plain-language help for the radio's settings, shown when hovering over a setting.

Keys are CHIRP's setting names for the A36plus driver. Menu numbers are the radio's own menu
(firmware 1.26). Sources: Talkpod's A36SE manual and the radio's menu list.
"""

import re
from dataclasses import dataclass

from gi.repository import GLib


@dataclass(frozen=True)
class Help:
    what: str
    use: str
    menu: str | None = None


S = Help

SETTINGS = {
    # --- Basic settings ----------------------------------------------------------------------
    "tot": S("Limits how long one press of PTT can transmit. When the time runs out the radio stops "
             "transmitting and beeps; let go of PTT and press it again to carry on.",
             "Stops a stuck PTT (radio squashed in a bag or under a car seat) from blocking a channel for "
             "everyone and flattening the battery, and stops the radio overheating. 60–120 seconds suits "
             "normal talk. Off means no limit.", "33"),
    "sql": S("Squelch: how strong a signal has to be before the speaker opens. 0 leaves the speaker open "
             "all the time (constant hiss); higher numbers only let stronger signals through.",
             "3–5 for everyday use. Lower it to hear distant, weak stations; raise it if noise or "
             "interference keeps opening the speaker. To check a weak signal without changing this, hold "
             "side key 3 (Monitor).", "02"),
    "vox": S("Voice-operated transmit: the radio transmits by itself when it hears you talk, without "
             "pressing PTT. 1 is the most sensitive, 9 the least.",
             "Hands-free use with a headset (driving, climbing, working with both hands). Leave it Off "
             "otherwise: wind, engine or background noise can key the radio up and block the channel.", "30"),
    "voxd": S("With VOX on, how long the radio keeps transmitting after you stop talking.",
              "Longer stops VOX cutting out between words; shorter frees the channel sooner. "
              "1.0–1.5 seconds is typical.", "31"),
    "voice": S("Spoken prompts when you change menus and modes.",
               "Turn off for quiet operation, or if the prompts are in a language you don't use.", "45"),
    "abr": S("How long the screen backlight stays on after the last key press. On keeps it lit all the time.",
             "Shorter saves battery. On is handy in a car mount or when it lives on its charger.", "44"),
    "vfomra": S("Whether display A (the upper line) shows a memory channel or a freely tuned frequency (VFO). "
                "Long-pressing MENU on the radio switches this too.",
                "Channel mode for everyday use with programmed channels, like UHF CB. Frequency (VFO) mode to "
                "type frequencies in directly, e.g. to listen around a band."),
    "vfomrb": S("Whether display B (the lower line) shows a memory channel or a freely tuned frequency (VFO).",
                "Usually the same as display A. With dual watch on, you could keep B in frequency mode for "
                "listening while A stays on your channels."),
    "screv": S("What scanning does when it finds a signal. Time (TO): stops for about 5 seconds, then moves "
               "on even if the signal continues. Carrier (CO): stays until the signal ends, waits about "
               "2 seconds so you can reply, then carries on. Search (SE): stops on the first signal and "
               "ends the scan.",
               "Carrier to follow conversations; Time for a quick look at which channels are busy; Search "
               "to find the active channel and stay on it.", "37"),
    "save": S("Battery saver: between checks for signals the receiver sleeps. Super and Deep sleep longer.",
              "Normal is a good default. Super or Deep make the battery last longer on standby but can clip "
              "the first word of a call. Off answers fastest, e.g. when you use it as a scanner.", "38"),
    "mdfa": S("In channel mode, what the big line on display A shows: the channel's name, its frequency, "
              "or its number. Long-pressing BACK on the radio cycles through these too.",
              "Name for named channels (CB05 EMERG, RPT01, …); Frequency when you want to see exactly "
              "where you are.", "11"),
    "mdfb": S("In channel mode, what display B shows: the channel's name, its frequency, or its number.",
              "Usually the same as display A.", "12"),
    "dtmfst": S("Whether you hear DTMF tones in your own speaker while they're sent: none, the keypad tones "
                "you type while transmitting, the automatic ID (PTT-ID) tones, or both.",
                "Turn on to confirm codes are going out (repeater control, selective calling); off for "
                "quiet. Doesn't change what other radios hear.", "27"),
    "pttlt": S("Delay between pressing PTT and the radio sending its automatic DTMF ID (PTT-ID).",
               "Only matters if PTT ID is used: it gives the receiving radio or repeater time to open "
               "before the code starts. 100–400 ms is usually enough.", "29"),
    "ani": S("Which entry of the ANI code list (in its own section below) is this radio's own identity "
             "code, sent by PTT-ID.",
             "Fleet or group use where each radio sends its own ID so others can tell who's calling. "
             "Not needed for normal UHF CB use.", "51"),
    "skey2_sp": S("What a short press of side key 2 (PF2) does. FM Radio: broadcast radio. TX Power Level: "
                  "switches high/low power. Scan. Search: reads the frequency and tone of a radio "
                  "transmitting close by, so you can copy it. NOAA Weather: US weather channels (there's no "
                  "such service in Australia). PTT B: makes this key a second PTT that transmits on "
                  "display B. REMOTE Scan: finds the CTCSS/DCS tone in use on the current frequency.",
                  "Put what you use most on the side keys, e.g. Scan or TX Power. PTT B is useful with dual "
                  "watch: PTT talks on A, this key talks on B.", "40"),
    "skey2_lp": S("What holding side key 2 (PF2) does. Same choices as the short press, plus SOS (alarm) "
                  "and DTMF (type DTMF codes to send).",
                  "A second function for the same key; Search (copy another radio's channel) is a handy "
                  "long-press choice.", "41"),
    "skey3_sp": S("What a short press of side key 3 (PF3) does. Same choices as side key 2. Holding side "
                  "key 3 is always Monitor (opens the squelch to hear weak signals).",
                  "TX Power Level is a popular choice so you can drop to low power for nearby contacts.",
                  "42"),
    "topkey_sp": S("What a short press of the top (orange) key does. Holding it starts the SOS alarm.",
                   "FM Radio or Scan are common choices. See Alarm Mode for what the SOS alarm sends.", "43"),
    "tone": S("Frequency of the tone burst sent when you press side key 3 while holding PTT.",
              "Some older repeaters need a short tone burst to open. 1750 Hz is the usual one (Europe and "
              "some amateur repeaters). UHF CB repeaters don't use it.", "28"),
    "ponmsg": S("What the screen shows when you switch on: the boot logo picture, or the battery voltage.",
                "Voltage is a quick battery check at power-on. Logo shows your own picture (see the "
                "Boot logo page).", "49"),
    "ste": S("Squelch tail elimination between handhelds: when you release PTT the radio sends a short "
             "signal that tells similar radios to mute straight away, so they don't hear a burst of noise "
             "('kshh') at the end of each over.",
             "Leave on when talking to radios like this one. Some other brands hear a short tone instead "
             "of silence; turn it off if people on those radios complain.", "36"),
    "rpste": S("Squelch tail elimination for repeaters: after a repeater stops relaying, the radio keeps "
               "its speaker muted for this long to hide the repeater's noise tail. (The radio's menu shows "
               "the same steps as 1–10.)",
               "Set it if you hear a burst of noise after every repeater transmission. Off lets you hear "
               "the tail, which confirms the repeater relayed you.", "22"),
    "rptrl": S("Repeater tail delay: lets you hear the repeater's tail for this long after it stops, as "
               "confirmation that it relayed your signal. (The radio's menu shows the same steps as 1–10.)",
               "Leave Off unless you want that audible confirmation when using repeaters.", "24"),
    "menuquit": S("How long a menu stays open with no key presses before the radio goes back to the "
                  "normal screen.",
                  "Longer while you're exploring menus; shorter so the radio doesn't sit in a menu.", "47"),
    "autolk": S("Locks the keypad automatically after this long without a key press. PTT and the side keys "
                "still work; hold the FM (lock) key to unlock.",
                "Stops accidental channel or setting changes in a pocket or on a belt.", "48"),
    "qtsave": S("When tone scanning (REMOTE Scan / Search) finds another radio's CTCSS/DCS tone, where the "
                "tone is saved: both receive and transmit (All), receive only, or transmit only.",
                "All to copy another radio's settings so you can talk to it; RX to only listen to that "
                "group.", "17"),
    "dualtx": S("Which display you transmit on when dual watch is on. Off: the one marked MAIN (the last "
                "one you selected). A or B: always that display, wherever MAIN is.",
                "Set it to A if you watch a second channel on B but always want to talk on A.", "10"),
    "almode": S("What the SOS alarm (hold the top key) does. Site: a loud alarm on this radio only. Tone: "
                "also transmits the alarm sound on the current channel. Code: transmits an alarm code.",
                "Site for a personal alarm. Tone and Code transmit on whatever channel you're on, so on UHF "
                "CB everyone on that channel hears it: only use them if your group expects it.", "39"),
    "roger": S("Sound sent when you release PTT: nothing, a short beep, or a 1200-baud data burst "
               "(MDC-1200/DC1200) that some systems use as an end-of-transmission ID.",
               "Off is normal on UHF CB (roger beeps annoy other users and some repeaters). A beep helps in "
               "noisy places so others know you've finished.", "00"),
    "alarmsound": S("Whether the SOS alarm makes a sound on the radio itself.",
                    "Off for a silent alarm (only transmitted, depending on Alarm Mode); on to attract "
                    "attention nearby."),
    "tdr": S("Dual watch: listens to both display A and display B. The radio flips between the two and "
             "stops on whichever has a signal.",
             "Keep an ear on a calling or emergency channel (e.g. CB 5, or your group's repeater) while you "
             "talk on another. Off gives faster single-channel response and slightly longer battery life.",
             "09"),
    "fmradio": S("Whether the broadcast FM radio (88–108 MHz, FM key) can be used.",
                 "Turn off to stop the FM key switching the radio to broadcast radio by accident."),
    "kblock": S("The keypad lock state stored in the radio (the same lock as holding the FM key).",
                "Normally off. On makes the radio start with its keypad locked."),
    "beep": S("Beeps when you press keys.",
              "Turn off for quiet operation.", "46"),
    "skey3_lp": S("Receive end beep: plays a short beep (MDC-1200 style) when the other station stops "
                  "talking. (CHIRP's internal name for this is misleading; it's the radio's RX END TAIL.)",
                  "Lets you know the other person has finished, especially on weak or noisy signals. "
                  "Leave Off if you don't want it.", "21"),
    "rxendtail": S("Phase shift of the CTCSS tone at the end of a transmission (120°, 180° or 240°). It's "
                   "another way to stop the noise burst at the end of each over, used by many repeaters "
                   "and commercial radios.",
                   "Only matters if you use CTCSS with repeaters or radios that use phase-shift tail "
                   "elimination (commonly 120° or 180°). Leave None if unsure.", "23"),
    "single_mode": S("Shows only one channel on screen instead of A and B. (8 W model firmware.)",
                     "A bigger, simpler display when you don't use dual watch."),
    "unlock_sw_ch": S("Lets the channel up/down keys keep working while the keypad is locked.",
                      "Lock everything except changing channels, e.g. in a car mount."),
    "dis_s_table": S("Shows the signal-strength meter. (8 W model firmware.)",
                     "Useful for judging how strong a station is."),
    # --- DTMF ----------------------------------------------------------------------------------
    "dtmf.dtmfon": S("How long each DTMF tone lasts when the radio sends codes.",
                     "Slower (longer) if the receiving system misses digits; faster to keep ID bursts short."),
    "dtmf.dtmfoff": S("The gap between DTMF tones.",
                      "Same as above: longer if digits get missed."),
    "pttid": S("When the radio sends its DTMF ID code: at the beginning of a transmission (BOT), at the "
               "end (EOT), or both. Each channel also has its own PTT ID setting.",
               "For group or fleet use where others need to see who's calling, or for systems that log "
               "IDs. Off for normal UHF CB use."),
}

PATTERNS = [
    (re.compile(r"^pttid/(\d+)\.code$"), S(
        "One of the 15 DTMF ID codes a channel can send as its PTT-ID (digits 0–9, A–D, * and #). Each "
        "channel's PTT ID Code setting picks which.",
        "Give each radio in a group its own code so others can tell who's calling.")),
    (re.compile(r"^anicodes/(\d+)\.code$"), S(
        "One entry in the radio's list of 60 ANI (identity) codes. The ANI setting picks which entry is "
        "this radio's own ID.",
        "Fleet or group use. Not needed for normal UHF CB use.", "51")),
    (re.compile(r"^aninames/(\d+)\.name$"), S(
        "A name for one of ANI codes 51–60 (shown as HAM1–HAM10 on the radio), e.g. a call sign.",
        "Name the radio after yourself or a call sign when it sends its ID.", "51")),
    (re.compile(r"^customnames/(\d+)\.name$"), S(
        "One of 30 ready-made channel names. On the radio, menu 19 (CH-NAME) lets you pick one of these "
        "for the current channel instead of typing a name. Blank ones show as NO NAMExx.",
        "Set up names you use often (e.g. CONVOY, CAMP, HOME) so you can name channels on the radio "
        "without a computer.", "19")),
]

# Section descriptions on the Settings page
GROUPS = {
    "dtmf": "Touch-tone (DTMF) codes the radio can send automatically when you press or release PTT "
            "(PTT-ID), and how fast it sends them. Only needed for group/fleet ID or DTMF-controlled systems.",
    "ani": "The radio's list of identity (ANI) codes. The ANI setting under Basic Settings picks which one "
           "is this radio's ID.",
    "custom": "Ready-made names you can give a channel from the radio's own menu (menu 19), without a "
              "computer.",
}

# Per-channel extras (channel editor)
EXTRAS = {
    "encrypt": S("Voice privacy on this channel: only radios with the same setting hear you clearly; "
                 "everyone else hears garble. It isn't secure encryption, and repeaters can't relay it.",
                 "Private chat between your own Talkpod radios. Leave Off on shared channels such as UHF CB.",
                 "32"),
    "scramble": S("Voice scrambler on this channel: only radios with the same scrambler setting hear you "
                  "clearly. Not secure, and won't pass through repeaters.",
                  "Casual privacy between compatible radios. Leave Off on shared channels."),
    "bcl": S("Busy channel lockout: stops you transmitting while someone else is already transmitting on "
             "this channel.",
             "Good manners on shared channels and repeaters. Turn off if constant noise on the channel keeps "
             "blocking you.", "35"),
    "pttid": S("Whether this channel sends the radio's DTMF ID when you press PTT (BOT), release it (EOT), "
               "or both.",
               "Group or fleet use where others need to see who's calling. Off for UHF CB.", "26"),
    "scode": S("Which of the 15 PTT-ID codes (DTMF settings) this channel sends.",
               "Pick the code assigned to this radio in your group.", "25"),
}

# Main channel-editor fields
FIELDS = {
    "name": S("The name shown on the radio when its display is set to show names (up to 12 letters).",
              "Short, recognisable names: CB10 4WD, RPT01, CAMP."),
    "rx": S("The frequency the radio listens on, in MHz (e.g. 476.425 for UHF CB channel 1).",
            "For repeater channels this is the repeater's output; the transmit side is set below."),
    "duplex": S("How the transmit frequency relates to the receive frequency. Simplex: both the same, "
                "radio to radio. Repeater +/−: transmit higher/lower by the offset, to reach a repeater. "
                "Split: transmit on any frequency you enter. Receive only: this channel can't transmit.",
                "Simplex for talking direct. Repeater + with 0.75 MHz for Australian UHF CB repeaters. "
                "Receive only for channels you must not transmit on (e.g. CB 22/23).", "04"),
    "offset": S("The difference between receive and transmit for repeater channels, or the transmit "
                "frequency itself for Split.",
                "0.75 MHz for Australian UHF CB repeaters (5 MHz for US GMRS, 0.6 MHz on 2 m amateur).", "05"),
    "power": S("Transmit power for this channel.",
               "High (5 W) for range; Low (1 W) for nearby contacts. It saves battery and keeps you from "
               "blocking more distant users.", "01"),
    "tmode": S("Tone squelch. None: hear everything on the channel. CTCSS on transmit: sends a sub-audible "
               "tone (opens repeaters that need one) but you still hear everything. CTCSS both ways: also "
               "keeps your speaker shut unless the other radio sends the same tone. DCS: the same idea "
               "using a digital code.",
               "None for UHF CB channels shared with everyone. CTCSS both ways or DCS to hear only your "
               "own group on a busy channel (others can still hear you).", "06/07, 13/14"),
    "tone": S("The CTCSS tone frequency. Both radios (or the repeater) must use the same one.",
              "Ask the repeater owner or your group which tone they use."),
    "dcs": S("The DCS code. Both radios must use the same code.", "Agree on one code within your group."),
    "pol": S("DCS polarity for transmit and receive. Normal is standard; inverted is for systems that need it.",
             "Leave Normal / normal unless a system specifies otherwise."),
    "width": S("Channel bandwidth. Narrow (12.5 kHz) or wide (25 kHz).",
               "Narrow for Australian UHF CB (80-channel plan) and most modern systems; wide for older "
               "25 kHz systems and CB channels 22/23.", "34"),
    "scan": S("Whether scanning stops on this channel.",
              "Leave repeater copies and data channels out of the scan so it doesn't stop twice on the same "
              "frequency.", "18"),
}


def lookup(name, table=None):
    """Help for a setting name (from SETTINGS, or the given table), or None."""
    table = SETTINGS if table is None else table
    if name in table:
        return table[name]
    if table is SETTINGS:
        for rx, h in PATTERNS:
            if rx.match(name):
                return h
    return None


def markup(title, h):
    """Tooltip text (Pango markup) for a setting."""
    esc = GLib.markup_escape_text
    head = f"<b>{esc(title)}</b>"
    if h.menu:
        head += f"   <small>radio menu {esc(h.menu)}</small>"
    return f"{head}\n\n{esc(h.what)}\n\n<b>When to use it</b>\n{esc(h.use)}"


def apply(row, title, h):
    """Attach help to an Adw row: the tooltip, and the menu number under the title."""
    if h is None:
        return
    row.set_tooltip_markup(markup(title, h))
    row.help_markup = row.get_tooltip_markup()
    if h.menu and hasattr(row, "set_subtitle") and not row.get_subtitle():
        row.set_subtitle(f"Radio menu {h.menu}")

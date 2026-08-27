#!/usr/bin/env python3
"""Refresh videos.js with every sump video YouTube will admit to having.

Run whenever the rotation feels stale: python3 scripts/refresh_playlist.py
Requires yt-dlp on PATH. Output is a JS file (not JSON) so the site also
works without fetch().

One YouTube search caps out near 600 results, so we mine from every angle:
  1. a relevance search for each of many sump-adjacent queries
  2. for queries with a rich vein, the date/views/rating sorts and the
     short/medium/long duration filters (each is a different slice)
  3. playlists and channels with "sump" in their name, expanded in full
  4. the whole back catalogue of every uploader with several sumps
  5. hashtag pages
  6. durations for shorts, which channel pages list without one
Everything is deduped by video id, kept only if the title is actually about
a sump, and merged with whatever videos.js already had. Raw fetches are
cached per day in .sumpcache/ so an interrupted run resumes where it stopped.
"""
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, quote_plus

QUERIES = [
    # the word itself
    "sump", "sumps", "sumping", "sump pump", "sump pumps", "the sump", "my sump",
    "sump video", "sump tour", "sump build", "sump diy", "sump how to", "sump explained",
    "sump fail", "sump problem", "sump fix", "sump repair", "sump clean", "sump cleaning",
    "sump install", "sump installation", "sump upgrade", "sump review", "sump unboxing",
    "sump test", "sump vs", "sump asmr", "sump sound", "sump noise", "sump timelapse",
    "sump overflow", "sump flood", "sump flooding", "sump leak", "sump smell", "sump 2024",
    "sump 2025", "sump 2026", "sump shorts", "sump meme", "sump song", "sump band",
    # basement / plumbing
    "sump pit", "sump basin", "sump crock", "sump liner", "sump hole", "sump well",
    "basement sump", "basement sump pump", "crawl space sump", "crawlspace sump pump",
    "sump pump install", "sump pump installation", "sump pump replacement",
    "sump pump replace", "sump pump repair", "sump pump not working", "sump pump fail",
    "sump pump failure", "sump pump failed", "sump pump broken", "sump pump stuck",
    "sump pump float switch", "sump pump float", "sump pump switch", "sump pump check valve",
    "sump pump discharge", "sump pump discharge line", "sump pump drain", "sump pump pipe",
    "sump pump pvc", "sump pump hose", "sump pump plumbing", "sump pump plumber",
    "plumbing sump", "plumber sump", "sump pump alarm", "sump pump battery backup",
    "sump battery backup", "sump pump backup", "sump pump water powered backup",
    "sump pump generator", "sump pump power outage", "sump pump running constantly",
    "sump pump running", "sump pump cycling", "sump pump short cycling", "sump pump loud",
    "sump pump noise", "sump pump quiet", "sump pump vibration", "sump pump humming",
    "sump pump smell", "sump pump clogged", "sump pump cleaning", "sump pump maintenance",
    "sump pump test", "sump pump testing", "sump pump inspection", "sump pump home inspection",
    "sump pump troubleshooting", "sump pump problems", "sump pump tips", "sump pump mistakes",
    "sump pump horror", "sump pump flood", "sump pump flooding", "sump pump rain",
    "sump pump storm", "sump pump hurricane", "sump pump heavy rain", "sump pump winter",
    "sump pump freeze", "sump pump frozen", "sump pump freezing", "sump pump snow melt",
    "sump pump cover", "sump pump lid", "sump pump sealed lid", "sump pump radon",
    "sump pump ice", "sump pump spring", "sump pump basin install", "sump pump pit install",
    "sump pump pedestal", "pedestal sump pump", "submersible sump pump", "sump pump 1/3 hp",
    "sump pump 1/2 hp", "sump pump 3/4 hp", "sump pump 1 hp", "sump pump cast iron",
    "sump pump review", "sump pump unboxing", "sump pump comparison", "best sump pump",
    "cheap sump pump", "sump pump vs", "sump pump asmr", "sump pump sound", "sump pump satisfying",
    "sump pump timelapse", "sump pump shorts", "sump pump diy", "sump pump how to",
    "sump pump explained", "sump pump 101", "sump pump for beginners", "sump pump wiring",
    "sump pump electrical", "sump pump outlet", "sump pump gfci", "sump pump smart",
    "sump pump wifi", "sump pump monitor", "sump pump sensor", "sump pump tesla",
    "sump pump french drain", "sump pump drain tile", "sump pump weeping tile",
    "sump pump waterproofing", "basement waterproofing sump", "sump pump foundation",
    "sump pump yard", "sump pump outdoor", "sump pump exterior", "sump pump outside",
    "sump pump garage", "sump pump driveway", "sump pump window well", "sump pump pool",
    "sump pump hot tub", "sump pump utility", "sump pump laundry", "laundry sump",
    "utility sink sump", "sink sump pump", "shower sump", "shower sump pump", "shower sump box",
    "bathroom sump", "basement bathroom sump", "toilet sump", "sump pump toilet",
    "sewage sump", "sewage sump pump", "sewage ejector sump", "ejector sump", "ejector pit sump",
    "grinder pump sump", "sump pump septic", "septic sump", "sump pump well water",
    "sump pump elevator", "elevator sump", "elevator pit sump", "sump pump commercial",
    "sump pump industrial", "sump pump apartment", "sump pump condo", "sump pump mobile home",
    "sump pump rv", "rv sump", "sump pump boat", "sump pump camper", "sump pump cabin",
    "sump pump shed", "sump pump barn", "sump pump chicken coop", "sump pump greenhouse",
    "sump pump dehumidifier", "dehumidifier sump", "condensate sump", "condensate sump pump",
    "hvac sump", "ac sump pump", "furnace sump", "boiler sump", "water heater sump",
    "sump pump dishwasher", "sump pump washing machine", "washing machine sump",
    "sump pump kitchen", "sump pump ice maker", "sump pump rain barrel", "rain barrel sump",
    "rainwater sump", "cistern sump", "sump pump cistern", "stormwater sump",
    "sump pump landlord", "sump pump tenant", "sump pump insurance", "sump pump code",
    # dishwashers
    "dishwasher sump", "dishwasher sump pump", "dishwasher sump assembly", "dishwasher sump replacement",
    "dishwasher sump gasket", "dishwasher sump seal", "dishwasher sump heater", "dishwasher sump filter",
    "dishwasher sump clogged", "dishwasher sump cleaning", "dishwasher sump removal",
    "dishwasher sump water", "dishwasher sump leak", "dishwasher sump motor", "dishwasher sump repair",
    "bosch dishwasher sump", "whirlpool dishwasher sump", "ge dishwasher sump", "lg dishwasher sump",
    "samsung dishwasher sump", "kitchenaid dishwasher sump", "frigidaire dishwasher sump",
    "maytag dishwasher sump", "miele dishwasher sump", "kenmore dishwasher sump",
    "beko dishwasher sump", "hotpoint dishwasher sump", "electrolux dishwasher sump",
    "dishwasher sump check valve", "dishwasher sump drain", "dishwasher sump mold",
    # pump brands & stores
    "zoeller sump pump", "zoeller m53", "wayne sump pump", "liberty sump pump", "liberty pumps sump",
    "basement watchdog sump", "watchdog sump pump", "everbilt sump pump", "ridgid sump pump",
    "superior pump sump", "flotec sump pump", "utilitech sump pump", "ryobi sump pump",
    "little giant sump pump", "hydromatic sump pump", "pentair sump pump", "sta-rite sump pump",
    "simer sump pump", "eco-flo sump pump", "acquaer sump pump", "vevor sump pump",
    "aquastrong sump pump", "prostormer sump pump", "sumpro", "sumpjet", "pitboss sump pump",
    "ion sump pump", "glentronics sump", "waterproofing sump pump", "sump pump home depot",
    "sump pump lowes", "sump pump costco", "sump pump menards", "sump pump harbor freight",
    "sump pump amazon", "sump pump walmart", "sump pump canadian tire", "sump pump screwfix",
    # aquariums / ponds
    "aquarium sump", "aquarium sump pump", "aquarium sump build", "aquarium sump setup",
    "aquarium sump diy", "aquarium sump explained", "aquarium sump design", "aquarium sump plumbing",
    "reef sump", "reef tank sump", "reef sump setup", "saltwater sump", "saltwater aquarium sump",
    "freshwater sump", "freshwater aquarium sump", "planted tank sump", "sump tank", "sump tank setup",
    "sump filter", "sump filtration", "sump filter aquarium", "sump filter diy", "diy sump",
    "diy sump filter", "diy aquarium sump", "diy reef sump", "sump refugium", "refugium sump",
    "sump baffle", "sump baffles", "sump chamber", "sump chambers", "sump design", "sump setup",
    "sump return pump", "sump return", "sump overflow box", "sump drain", "herbie overflow sump",
    "bean animal sump", "durso sump", "sump skimmer", "sump protein skimmer", "sump filter sock",
    "sump filter roller", "sump media", "sump bio media", "sump heater", "sump ato", "sump auto top off",
    "sump water level", "sump evaporation", "sump light", "sump chaeto", "sump algae", "sump macroalgae",
    "sump cleanup crew", "sump acrylic", "sump glass", "sump plastic tub", "sump tote", "sump bucket",
    "sump 10 gallon", "sump 20 gallon", "sump 20 long", "sump 29 gallon", "sump 40 breeder",
    "sump 55 gallon", "sump 75 gallon", "sump 100 gallon", "sump 120 gallon", "sump 200 gallon",
    "nano sump", "nano reef sump", "trigger systems sump", "eshopps sump", "red sea sump",
    "waterbox sump", "innovative marine sump", "fiji cube sump", "bashsea sump", "synergy reef sump",
    "sump vs canister", "sump vs hob", "sump vs sump", "sump micro bubbles", "sump bubbles",
    "sump noise aquarium", "sump quiet", "sump flood aquarium", "sump overflow aquarium",
    "sump power outage", "sump siphon", "sump check valve", "sump gate valve", "sump ball valve",
    "sump pvc", "sump plumbing aquarium", "sump manifold", "sump dosing", "sump reactor",
    "sump uv", "sump fuge", "sump frag tank", "sump coral", "sump fish", "sump shrimp",
    "sump snail", "sump crab", "sump mantis", "sump pods", "sump copepods", "sump live rock",
    "sump rubble", "sump sand", "sump deep sand bed", "sump rock", "sump mangrove",
    "koi pond sump", "pond sump", "pond sump pump", "pond sump filter", "sump pond diy",
    "turtle tank sump", "axolotl sump", "cichlid sump", "african cichlid sump", "discus sump",
    "monster fish sump", "goldfish sump", "betta sump", "shrimp tank sump", "fish room sump",
    "fishroom sump", "central sump", "central sump system", "rack sump", "aquaponics sump",
    "aquaponics sump tank", "hydroponics sump", "hydroponic sump", "sump tank hydroponics",
    "sump pump aquaponics", "fountain sump", "water feature sump", "pondless waterfall sump",
    "waterfall sump", "sump basin waterfall", "sump reservoir", "pool sump", "pool main drain sump",
    "sump vault", "sump pump pond", "sump tank fish", "sump for fish tank", "sump for reef",
    "sump for aquarium", "sump for pond", "sump for turtle", "sump upgrade aquarium", "sump rebuild",
    "sump redo", "sump tear down", "sump remodel", "sump makeover", "sump reorganize",
    # engines / vehicles
    "oil sump", "engine sump", "car sump", "sump plug", "sump nut", "sump bolt", "sump plug removal",
    "sump plug stripped", "stripped sump plug", "sump plug thread repair", "sump plug helicoil",
    "sump plug washer", "sump plug leak", "sump plug magnet", "magnetic sump plug", "sump plug torque",
    "sump plug stuck", "sump plug rounded", "sump plug tap", "sump plug oversize", "sump plug drill",
    "sump pan", "oil pan sump", "sump gasket", "sump gasket replacement", "sump gasket leak",
    "sump leak repair", "sump oil leak", "sump reseal", "sump removal", "sump replacement",
    "sump off", "sump refit", "sump cracked", "cracked sump", "cracked sump repair", "sump crack",
    "sump weld", "sump welding", "sump jb weld", "sump epoxy", "sump damage", "damaged sump",
    "sump hit", "sump hole repair", "sump holed", "sump dent", "sump scrape", "sump smashed",
    "sump guard", "sump guard install", "sump guard fitting", "sump guard 4x4", "sump guard motorcycle",
    "sump guard rally", "sump guard steel", "sump guard aluminium", "sump guard test", "sump guard review",
    "sump guard diy", "sumpguard", "bash plate sump", "sump plate", "sump protector", "sump protection",
    "sump shield", "sump skid plate", "sump bash plate", "dry sump", "dry sump system",
    "dry sump tank", "dry sump pump", "dry sump conversion", "dry sump kit", "dry sump explained",
    "dry sump vs wet sump", "wet sump", "wet sump vs dry sump", "dry sump oil", "dry sump install",
    "dry sump race", "dry sump racing", "dry sump ls", "dry sump v8", "dry sump porsche",
    "dry sump motorcycle", "dry sump bmw", "dry sump honda", "dry sump subaru", "dry sump rotary",
    "dry sump drift", "dry sump track", "dry sump build", "dry sump problems", "dry sump scavenge",
    "baffled sump", "sump baffle plate", "sump baffle engine", "sump extension", "sump spacer",
    "sump adapter", "sump kit", "sump conversion", "sump swap", "sump modification", "sump mod",
    "rear sump", "front sump", "mid sump", "sump depth", "sump capacity", "sump oil level",
    "sump temperature", "sump temp", "sump cooler", "sump window", "sump pickup", "oil pickup sump",
    "sump strainer", "sump filter engine", "sump oil filter", "sump drain", "sump drain plug",
    "sump oil change", "sump oil drain", "oil sump drain", "sump oil extractor", "sump pump oil extractor",
    "sump oil pump", "transmission sump", "gearbox sump", "gearbox sump plug", "diff sump",
    "transmission sump plug", "auto transmission sump", "sump torque", "sump bolts torque",
    "sump sealant", "sump silicone", "sump rtv", "sump gasket sealant", "sump gasket diy",
    "sump gasket ford", "sump gasket vw", "sump gasket bmw", "sump gasket toyota", "sump gasket honda",
    "sump gasket nissan", "sump gasket mercedes", "sump gasket audi", "sump gasket peugeot",
    "sump gasket vauxhall", "sump gasket holden", "sump gasket subaru", "sump gasket land rover",
    "bmw sump", "vw sump", "ford sump", "holden sump", "toyota sump", "honda sump", "subaru sump",
    "nissan sump", "land rover sump", "landrover sump", "mini sump", "mazda sump", "audi sump",
    "mercedes sump", "peugeot sump", "citroen sump", "renault sump", "vauxhall sump", "opel sump",
    "fiat sump", "alfa sump", "hyundai sump", "kia sump", "volvo sump", "jaguar sump", "lotus sump",
    "porsche sump", "ferrari sump", "skoda sump", "seat sump", "suzuki sump", "mitsubishi sump",
    "isuzu sump", "hilux sump", "ranger sump", "navara sump", "defender sump", "discovery sump",
    "jeep sump", "jimny sump", "landcruiser sump", "patrol sump", "prado sump", "commodore sump",
    "falcon sump", "ls sump", "ls1 sump", "ls swap sump", "k20 sump", "b series sump", "sr20 sump",
    "rb sump", "rb25 sump", "2jz sump", "1jz sump", "4age sump", "ej sump", "ej20 sump", "ej25 sump",
    "duratec sump", "pinto sump", "zetec sump", "vr6 sump", "tdi sump", "1.9 tdi sump", "1.6 hdi sump",
    "m50 sump", "m52 sump", "n47 sump", "b58 sump", "s54 sump", "rover v8 sump", "vtec sump",
    "hemi sump", "small block sump", "big block sump", "windsor sump", "cleveland sump", "sbc sump",
    "sbf sump", "bbc sump", "coyote sump", "barra sump", "rotary sump", "13b sump", "wankel sump",
    "tractor sump", "mower sump", "lawnmower sump", "lawn mower sump", "ride on mower sump",
    "boat sump", "outboard sump", "jet ski sump", "generator sump", "chainsaw sump", "kart sump",
    "karting sump", "quad sump", "atv sump", "dirt bike sump", "motorbike sump", "motorcycle sump",
    "bike sump", "ktm sump", "ducati sump", "harley sump", "triumph sump", "royal enfield sump",
    "enfield sump", "bullet sump", "classic 350 sump", "himalayan sump", "interceptor sump",
    "meteor sump", "hunter 350 sump", "bmw gs sump", "gs sump", "africa twin sump", "tenere sump",
    "kawasaki sump", "yamaha sump", "honda bike sump", "scooter sump", "vespa sump", "lambretta sump",
    "pit bike sump", "husqvarna sump", "beta sump", "sherco sump", "gasgas sump", "trials bike sump",
    "enduro sump", "motocross sump", "adventure bike sump", "sump guard bike", "sump guard scooter",
    "sump bash", "sump skid", "sump bashed", "sump ripped", "sump torn", "sump hole", "sump split",
    "sump vibration", "sump rust", "rusty sump", "sump rot", "rotten sump", "sump repair kit",
    "sump plug repair kit", "sump plug kit", "sump plug set", "sump plug key", "sump plug tool",
    "sump plug socket", "sump key", "sump spanner", "sump wrench", "sump drain tool",
    "sump pump car", "sump pump engine", "sump pump oil", "sump pump extractor", "oil sump pump",
    "engine sump pump", "engine oil sump", "oil sump leak", "oil sump gasket", "oil sump repair",
    "oil sump removal", "oil sump replacement", "oil sump cleaning", "oil sump sludge", "sump sludge",
    "aluminium sump", "alloy sump", "steel sump", "cast sump", "fabricated sump", "custom sump",
    "race sump", "racing sump", "rally sump", "drift sump", "track sump", "sump for racing",
    "aircraft sump", "airplane sump", "aircraft fuel sump", "fuel sump", "fuel tank sump",
    "sump the fuel", "sumping fuel", "fuel sump drain", "sump drain aircraft", "gascolator sump",
    "sump cup", "fuel sump cup", "cessna sump", "cessna 172 sump", "piper sump", "cirrus sump",
    "preflight sump", "sump fuel check", "water in fuel sump", "sump the tanks", "sump tanks",
    "diesel sump", "diesel tank sump", "fuel sump boat", "boat fuel sump", "bilge sump", "sump bilge",
    "helicopter sump", "sump chip detector", "engine chip detector sump", "turbine sump",
    "jet engine sump", "sump pressure", "sump vent", "sump breather", "sump scavenge",
    # mines, industry, construction
    "mining sump", "mine sump", "underground sump", "underground mine sump", "sump dewatering",
    "sump pump mining", "coal mine sump", "gold mine sump", "quarry sump", "sump dredging",
    "sump excavation", "tunnel sump", "sump construction", "sump concrete", "concrete sump",
    "precast sump", "sump manhole", "sump wastewater", "wet well sump", "lift station sump",
    "sump station", "drainage sump", "sump drainage", "sump catch basin", "sump chamber construction",
    "sump lift", "parking garage sump", "sump inspection", "confined space sump", "sump cleaning vacuum",
    "sump vac", "sump vacuum", "sump vac truck", "vacuum truck sump", "sump grease", "grease sump",
    "sump tank cleaning", "sump silt", "sump sediment", "sump slurry", "sump mud", "sump muck",
    "sump digging", "dig sump", "digging a sump", "sump excavator", "sump backhoe", "sump trench",
    "sump pit construction", "sump pit design", "sump pit cleaning", "sump pit pump", "sump pit diy",
    "sump pit cover", "sump pit lid", "sump pit basement", "sump pit mining", "sump pit garage",
    "sump pit industrial", "sump pit sewage", "sump pit stormwater", "sump pit building",
    "coolant sump", "cnc sump", "cnc sump cleaning", "machine sump", "machine tool sump",
    "machine sump cleaning", "coolant sump cleaner", "sump sucker", "sump cleaner", "sump skimmer oil",
    "sump oil skimmer", "tramp oil sump", "coolant sump pump", "lathe sump", "mill sump",
    "sump cutting fluid", "sump biocide", "sump bacteria", "sump stink", "sump smell cnc",
    "hydraulic sump", "hydraulic sump tank", "reservoir sump", "compressor sump", "sump compressor",
    "vacuum pump sump", "sump lubrication", "sump lube", "oil sump industrial", "sump heater industrial",
    "sump pump station", "sump pump wet well", "sump pump lift station", "sump pump manhole",
    "sump pump sewer", "sump pump stormwater", "sump pump quarry", "sump pump mine",
    "sump pump construction", "sump pump excavation", "sump pump trench", "sump pump dewatering",
    "dewatering sump pump", "sump pump trash", "trash pump sump", "sump pump diesel",
    "sump pump gas", "sump pump petrol", "sump pump solar", "solar sump pump", "sump pump 12v",
    "12v sump pump", "sump pump 240v", "sump pump 110v", "sump pump 3 phase", "sump pump control panel",
    "sump pump duplex", "duplex sump", "sump pump triplex", "sump level control", "sump level sensor",
    "sump level switch", "sump float switch", "sump alarm", "sump high level alarm", "sump controller",
    "sump plc", "sump scada", "sump automation", "sump arduino", "sump esp32", "sump home assistant",
    "sump monitoring", "sump monitor", "sump sensor", "sump data", "sump graph", "sump log",
    "oil rig sump", "drilling sump", "mud sump", "sump pit drilling", "oilfield sump", "sump tank oilfield",
    "refinery sump", "sump refinery", "sump tank industrial", "sump tank cleaning industrial",
    "gas station sump", "fuel dispenser sump", "dispenser sump", "under dispenser sump", "sump ust",
    "tank sump", "sump sensor gas station", "sump testing gas station", "sump hydrostatic test",
    "sump integrity test", "turbine sump gas station", "sump fibreglass", "sump fiberglass",
    "sump penetration", "sump boot", "sump entry boot", "sump fitting",
    # caves / outdoors / other
    "cave sump", "sump cave", "sump diving", "sump dive", "cave diving sump", "sump rescue",
    "sump exploration", "sump 1", "sump 2", "sump 3", "sump 4", "sump 5", "sump one", "sump two",
    "caving sump", "sump free diving", "sump free dive", "free dive sump", "sump ducks", "duck sump",
    "sump passage", "sump pool cave", "sump underwater", "sump ogof", "ogof sump", "sump pot",
    "sump cavern", "sump line", "sump dive line", "sump diver", "sump divers", "sump dived",
    "swildons sump", "swildon's sump", "wookey sump", "ogof ffynnon ddu sump", "ofd sump",
    "dan yr ogof sump", "peak cavern sump", "speedwell sump", "keld head sump", "kingsdale sump",
    "sump rescue cave", "cave rescue sump", "sump thailand cave", "sump cave rescue thailand",
    "sump sea", "sump lake", "sump river", "sump creek", "sump stream", "sump spring", "sump karst",
    "sump geology", "sump hydrology", "sump water table", "sump minecraft", "sump roblox",
    "sump game", "sump gaming", "sump horror game", "sump level game", "sump the game",
    "sump metal", "sump doom", "sump black metal", "sump music", "sump album", "sump live",
    "sump lyrics", "sump art", "sump painting", "sump poem", "sump story", "sump history",
    "sump definition", "sump meaning", "sump pronunciation", "sump word", "what is a sump",
    "what is sump", "what is a sump pump", "what does sump mean", "sump slang", "sump etymology",
    "sump english", "sump language", "sump in hindi", "sump hindi", "sump tamil", "sump telugu",
    "sump malayalam", "sump kannada", "sump marathi", "sump bengali", "sump urdu", "sump gujarati",
    "sump tank cleaning", "sump tank cleaning india", "sump cleaning india", "sump water tank",
    "sump tank water", "sump tank construction", "sump tank house", "sump tank motor",
    "sump motor", "sump motor repair", "sump motor installation", "sump pump india",
    "sump tank design", "sump tank size", "sump tank waterproofing", "sump tank leakage",
    "sump tank cleaning service", "underground sump tank", "sump tank bangalore", "sump tank chennai",
    "sump tank hyderabad", "sump tank kerala", "sump tank tamil", "sump tank telugu",
    "sump tank kannada", "sump tank malayalam", "sump tank hindi", "sump to overhead tank",
    "sump overhead tank", "sump borewell", "borewell sump", "sump pump automatic", "automatic sump",
    "sump automatic controller", "sump water level controller", "sump level indicator",
    "sump tank alarm", "sump tank float", "sump tank pump", "sump tank motor automatic",
    "sump australia", "sump uk", "sump nz", "sump canada", "sump ireland", "sump south africa",
    "sump aussie", "sump 4wd", "sump 4x4", "sump offroad", "sump off road", "sump overland",
    "sump camping", "sump caravan", "caravan sump", "sump pump caravan", "sump grey water",
    "grey water sump", "greywater sump", "gray water sump", "sump for shower", "sump for sink",
    "sump for laundry", "sump for basement", "sump for garage", "sump for crawl space",
    "sump for pool", "sump for hot tub", "sump for fountain", "sump for rain", "sump for flood",
    "sump for water", "sump pump for", "sump ai", "sump robot", "sump drone", "sump camera",
    "sump gopro", "sump 360", "sump vlog", "sump podcast", "sump interview", "sump documentary",
    "sump news", "sump report", "sump science", "sump engineering", "sump physics", "sump math",
    "sump calculation", "sump sizing", "sump size", "sump volume", "sump flow", "sump flow rate",
    "sump head", "sump gph", "sump lph", "sump turnover", "sump pump sizing", "sump pump size",
    "sump pump gph", "sump pump head", "sump pump curve", "sump pump flow", "sump pump capacity",
    "sump pump horsepower", "sump pump hp", "sump pump watts", "sump pump amps", "sump pump energy",
    "sump pump cost", "sump pump price", "sump pump cheap", "sump pump expensive", "sump pump sale",
    "sump pump deal", "sump pump free", "sump pump used", "sump pump old", "sump pump vintage",
    "sump pump antique", "sump pump history", "sump pump restoration", "sump pump rebuild",
    "sump pump teardown", "sump pump disassembly", "sump pump inside", "sump pump motor",
    "sump pump impeller", "sump pump seal", "sump pump bearing", "sump pump capacitor",
    "sump pump screen", "sump pump intake", "sump pump clog", "sump pump debris", "sump pump rocks",
    "sump pump gravel", "sump pump sand", "sump pump iron", "sump pump iron bacteria",
    "sump pump slime", "sump pump mold", "sump pump bleach", "sump pump vinegar", "sump pump chemical",
    "sump pump bugs", "sump pump spiders", "sump pump frog", "sump pump snake", "sump pump mouse",
    "sump pump rat", "sump pump cat", "sump pump dog", "sump pump kids", "sump pump baby",
    "sump pump prank", "sump pump funny", "sump pump fail funny", "sump pump comedy", "sump pump skit",
    "sump pump song", "sump pump rap", "sump pump music", "sump pump remix", "sump pump meme",
    "sump pump tiktok", "sump pump reel", "sump pump short", "sump pump live", "sump pump stream",
]

QUERIES = list(dict.fromkeys(QUERIES))

# playlists and channels with these in the name get expanded in full
COLLECTION_QUERIES = [
    "sump", "sumps", "sump pump", "sump pumps", "aquarium sump", "reef sump", "sump tank",
    "sump filter", "sump refugium", "diy sump", "oil sump", "engine sump", "sump guard",
    "sump plug", "dry sump", "dishwasher sump", "sump pit", "cave sump", "sump diving",
    "mine sump", "sump cleaning", "sump tank cleaning",
]
HASHTAGS = [
    "sump", "sumps", "sumppump", "sumppumps", "sumppit", "sumpbasin", "aquariumsump", "reefsump",
    "sumptank", "sumpfilter", "sumprefugium", "diysump", "drysump", "wetsump", "oilsump",
    "enginesump", "sumpguard", "sumpplug", "sumpgasket", "dishwashersump", "cavesump",
    "sumpdiving", "sumptankcleaning", "sumpcleaning", "sumpmotor",
]

PER_SEARCH = 500      # youtube stops paging near 600 anyway
DEEP_MIN_HITS = 40    # thinner veins don't get the sort/duration passes
CHANNEL_MIN_HITS = 6  # uploaders with this many sumps get their whole catalogue scanned
CHANNEL_CAP = 2000
PLAYLIST_CAP = 1000
WORKERS = 8
MIN_SEC = 20      # skip near-empty clips
MAX_SEC = 1800    # skip the 10-hour sump-noise loops so they can't eat the schedule

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "videos.js"
CACHE = ROOT / ".sumpcache" / time.strftime("%Y-%m-%d", time.gmtime())

# "sump" hides inside words that have nothing to do with sumps
SUMPWORD = re.compile(r"\w*sump\w*", re.I)
NOT_SUMP = re.compile(r"sumpt|sumpah|sumpa\b|sumpf|sumpter", re.I)


def is_sump(title: str) -> bool:
    return any(not NOT_SUMP.search(w) for w in SUMPWORD.findall(title))


def sp(sort: int = 0, duration: int = 0, upload: int = 0, kind: int = 1) -> str:
    """YouTube's search-filter blob: protobuf {1: sort, 2: {1: upload, 2: type, 3: duration}}."""
    filt = (b"\x08" + bytes([upload]) if upload else b"") + b"\x10" + bytes([kind])
    filt += b"\x18" + bytes([duration]) if duration else b""
    raw = (b"\x08" + bytes([sort]) if sort else b"") + b"\x12" + bytes([len(filt)]) + filt
    return quote(quote(base64.b64encode(raw).decode()))  # youtube double-encodes it


SORT_RATING, SORT_DATE, SORT_VIEWS = 1, 2, 3
DUR_SHORT, DUR_LONG, DUR_MEDIUM = 1, 2, 3
UP_MONTH, UP_YEAR = 4, 5
KIND_VIDEO, KIND_CHANNEL, KIND_PLAYLIST = 1, 2, 3
# youtube ignores the date sort unless an upload window comes with it
DEEP_VARIANTS = [
    (SORT_VIEWS, 0, 0), (SORT_RATING, 0, 0), (SORT_DATE, 0, UP_MONTH), (SORT_DATE, 0, UP_YEAR),
    (0, DUR_SHORT, 0), (0, DUR_MEDIUM, 0), (0, DUR_LONG, 0),
]


def search_url(query: str, sort: int = 0, duration: int = 0, upload: int = 0, kind: int = KIND_VIDEO) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={sp(sort, duration, upload, kind)}"


def fetch(url: str, cap: int) -> list[dict]:
    key = hashlib.sha1(f"{url}|{cap}".encode()).hexdigest()[:20]
    path = CACHE / f"{key}.jsonl"
    if path.exists():
        return [json.loads(line) for line in path.read_text().splitlines()]
    proc = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-j", "--no-warnings", "--playlist-end", str(cap), url],
        capture_output=True, text=True,
    )
    entries = []
    for line in proc.stdout.splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if proc.returncode != 0 and not entries and "does not have a" not in proc.stderr:  # no shorts tab is final
        err = (proc.stderr.strip().splitlines() or ["?"])[-1]
        print(f"  ! {url[:80]}: {err[:120]}", file=sys.stderr)
        return []  # not cached, so a rerun retries it
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
    return entries


def probe(ids: list[str]) -> list[dict]:
    """Full metadata for videos the flat listings gave no duration for."""
    path = CACHE / f"probe-{hashlib.sha1(' '.join(ids).encode()).hexdigest()[:20]}.jsonl"
    if path.exists():
        return [json.loads(line) for line in path.read_text().splitlines()]
    proc = subprocess.run(
        ["yt-dlp", "--skip-download", "--no-warnings", "--ignore-errors",
         "--print", "%(id)s %(duration)s %(live_status)s"]
        + [f"https://www.youtube.com/watch?v={v}" for v in ids],
        capture_output=True, text=True,
    )
    entries = []
    for line in proc.stdout.splitlines():
        vid, dur, live = line.split(" ", 2)
        if dur != "NA":
            entries.append({"id": vid, "duration": float(dur), "live_status": live, "ie_key": "Youtube"})
    if not entries and proc.returncode != 0:
        return []  # not cached, so a rerun retries it
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return entries


def fetch_many(jobs: list[tuple[str, int]]) -> list[list[dict]]:
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(lambda j: fetch(*j), jobs))


class Hoard:
    """Every sump seen so far, keyed by id, plus a tally per stage."""

    def __init__(self) -> None:
        self.videos: dict[str, dict] = {}
        self.channels: Counter = Counter()
        self.undated: dict[str, str] = {}
        self.skipped = 0

    def add(self, entries: list[dict]) -> int:
        added = 0
        for e in entries:
            vid, dur, title = e.get("id"), e.get("duration"), (e.get("title") or "").strip()
            if not vid or vid in self.videos or not is_sump(title):
                continue
            if e.get("live_status") in ("is_live", "is_upcoming"):
                self.skipped += 1
                continue
            if dur is None:
                if e.get("ie_key") == "Youtube":
                    self.undated[vid] = title
                continue
            if not (MIN_SEC <= dur <= MAX_SEC):
                self.skipped += 1
                continue
            self.videos[vid] = {"id": vid, "title": title, "duration": int(dur)}
            if e.get("channel_id"):
                self.channels[e["channel_id"]] += 1
            added += 1
        return added

    def stage(self, name: str, batches: list[list[dict]]) -> None:
        added = sum(self.add(b) for b in batches)
        print(f"{name}: +{added} -> {len(self.videos)} sumps")


def load_existing() -> list[dict]:
    if not OUT.exists():
        return []
    text = OUT.read_text()
    payload = json.loads(text[text.index("{"):text.rindex("}") + 1])
    return payload.get("videos", [])


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    hoard = Hoard()
    start = time.time()

    # videos.js already has last time's haul; re-filter it in case the rules tightened
    old = load_existing()
    hoard.stage(f"existing ({len(old)} on disk)", [old])

    print(f"1/6 relevance search, {len(QUERIES)} queries...")
    batches = fetch_many([(search_url(q), PER_SEARCH) for q in QUERIES])
    hits = {q: sum(is_sump(e.get("title") or "") for e in b) for q, b in zip(QUERIES, batches)}
    hoard.stage("relevance", batches)

    deep = [q for q in QUERIES if hits[q] >= DEEP_MIN_HITS]
    print(f"2/6 sort/duration slices of {len(deep)} rich queries x {len(DEEP_VARIANTS)}...")
    jobs = [(search_url(q, s, d, u), PER_SEARCH) for q in deep for s, d, u in DEEP_VARIANTS]
    hoard.stage("slices", fetch_many(jobs))

    print("3/6 sump-named playlists and channels...")
    found = fetch_many([(search_url(q, kind=KIND_PLAYLIST), 200) for q in COLLECTION_QUERIES])
    playlists = {e["id"]: e["url"] for b in found for e in b if is_sump(e.get("title") or "")}
    hoard.stage(f"{len(playlists)} playlists", fetch_many([(u, PLAYLIST_CAP) for u in playlists.values()]))
    found = fetch_many([(search_url(q, kind=KIND_CHANNEL), 100) for q in COLLECTION_QUERIES])
    named = {e["id"] for b in found for e in b if is_sump(e.get("title") or "")}
    scanned = set(named)
    hoard.stage(f"{len(named)} channels", fetch_many(
        [(f"https://www.youtube.com/channel/{c}/{tab}", CHANNEL_CAP) for c in named for tab in ("videos", "shorts")]))

    prolific = [c for c, n in hoard.channels.most_common() if n >= CHANNEL_MIN_HITS and c not in scanned]
    print(f"4/6 back catalogues of {len(prolific)} prolific sump uploaders...")
    hoard.stage("catalogues", fetch_many(
        [(f"https://www.youtube.com/channel/{c}/{tab}", CHANNEL_CAP) for c in prolific for tab in ("videos", "shorts")]))

    print(f"5/6 {len(HASHTAGS)} hashtags...")
    hoard.stage("hashtags", fetch_many([(f"https://www.youtube.com/hashtag/{h}", PER_SEARCH) for h in HASHTAGS]))

    undated = sorted(v for v in hoard.undated if v not in hoard.videos)
    print(f"6/6 durations for {len(undated)} undated sumps (mostly shorts)...")
    batches = [undated[i:i + 25] for i in range(0, len(undated), 25)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        probed = list(pool.map(probe, batches))
    hoard.stage("undated", [[dict(e, title=hoard.undated[e["id"]]) for e in b] for b in probed])

    videos = sorted(hoard.videos.values(), key=lambda v: v["id"])
    if len(videos) < 10:
        print(f"only {len(videos)} usable videos found; not overwriting", file=sys.stderr)
        return 1

    total = sum(v["duration"] for v in videos)
    payload = {
        "generated": time.strftime("%Y-%m-%d", time.gmtime()),
        "query": " | ".join(QUERIES),
        "videos": videos,
    }
    OUT.write_text(
        "// generated by scripts/refresh_playlist.py -- do not edit by hand\n"
        "window.SUMP = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    )
    print(f"wrote {OUT.name}: {len(videos)} sumps, {total / 3600:.1f}h of footage "
          f"({hoard.skipped} skipped for length/liveness) in {(time.time() - start) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())

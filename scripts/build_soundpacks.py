#!/usr/bin/env python3
"""
Build modular Sound Packs (.zip with decoded .sf2 files), soundpacks.json manifest,
extended android/mobile_catalog.json (including the 22 Audio Evolution SoundFonts / 47 new timbres
and Nord Red Ambient Pad in Worship Immersion), and optimized PNG thumbnails (android/soundimages/).
"""
import hashlib
import io
import json
import os
import sys
import zipfile
from PIL import Image

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_APK = os.path.join(ROOT_DIR, "build", "base_template.apk")
OUT_PACKS_DIR = os.path.join(ROOT_DIR, "dist", "soundpacks")
OUT_IMAGES_DIR = os.path.join(ROOT_DIR, "android", "soundimages")
OUT_MANIFEST = os.path.join(ROOT_DIR, "soundpacks.json")
OUT_CATALOG = os.path.join(ROOT_DIR, "android", "mobile_catalog.json")

REPO = "vmarconivieira/MIDIControl"
PACKS_TAG = "soundpacks-v1"
BASE_URL = f"https://github.com/{REPO}/releases/download/{PACKS_TAG}"


def drive_url(file_id: str) -> str:
    return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"


CORE_ASSET_FILES = {
    "soundbank/1_-_Model_D_1983.numares",
    "soundbank/1_-_EP-Mark_I.numares",
    "soundbank/5_-_SynthPad2.numares",
    "soundbank/1_-_PURE_B3.numares",
}

# Published GitHub Release soundpacks-v1 zip packs (exact sizeBytes & sha256 on soundpacks-v1)
PACK_DEFS = [
    {
        "id": "pack_apiano_extra",
        "name": "Pianos Acústicos",
        "description": "The Upright, CP E-Grand",
        "category": "1 - A_PIANO",
        "published_size": 22322226,
        "published_sha256": "5861f0929be2672a6b9e272a8bc8e56ded346cef1da646c8e99146e418654821",
        "asset_files": [
            "soundbank/3_-_The_Upright.numares",
            "soundbank/4_-_CP_E-Grand.numares",
        ],
    },
    {
        "id": "pack_epiano_extra",
        "name": "Pianos Elétricos & FM",
        "description": "EP-Mark II, Wurly 200/255, FM-EP 1–4",
        "category": "2 - E_PIANO",
        "published_size": 38369258,
        "published_sha256": "2112cffdeaa7d23729757309c20996fc36e620eb188a48a09e68459841752d61",
        "asset_files": [
            "soundbank/2_-_EP-Mark_II.numares",
            "soundbank/3_-_Wurly_200.numares",
            "soundbank/4_-_Wurly_255.numares",
            "soundbank/5_-_FM-EP1.numares",
            "soundbank/6_-_FM-EP2.numares",
            "soundbank/7_-_FM-EP3.numares",
            "soundbank/8_-_FM-EP4.numares",
        ],
    },
    {
        "id": "pack_strings_pads",
        "name": "Cordas, Corais & Pads",
        "description": "Strings Ensemble/Section, Cellos, SynthPad1, VoicePad, SynChoir",
        "category": "4 - STRINGS_PADS",
        "published_size": 39659280,
        "published_sha256": "92b1fae2c47874e334668b16e31f4b0e598450764c70b3f520b5d22bef8540c1",
        "asset_files": [
            "soundbank/1_-_StringsEnsemble.numares",
            "soundbank/2_-_StringsSection.numares",
            "soundbank/3_-_Cellos.numares",
            "soundbank/4_-_SynthPad1.numares",
            "soundbank/6_-_VoicePad.numares",
            "soundbank/7_-_SynChoir.numares",
        ],
    },
    {
        "id": "pack_keys_mallets",
        "name": "Keys, Mallets & Acordeons",
        "description": "Clavinet, Harpsi, Vibes, Marimba, Celesta, Cassotto, MasteFisa, Musette",
        "category": "3 - KEYS_MALLETS",
        "published_size": 42500960,
        "published_sha256": "53311e5fbba05466ce92bf56be7ff9edfc5926ba67757e14c23bd091e51279e3",
        "asset_files": [
            "soundbank/1_-_Clavinet.numares",
            "soundbank/2_-_Harpsi.numares",
            "soundbank/3_-_Vibes.numares",
            "soundbank/4_-_Marimba.numares",
            "soundbank/5_-_Celesta.numares",
            "soundbank/6_-_Cassotto.numares",
            "soundbank/7_-_MasteFisa.numares",
            "soundbank/8_-_Musette.numares",
        ],
    },
    {
        "id": "pack_organs",
        "name": "Órgãos B3, Pipe & FM",
        "description": "19 órgãos adicionais (Jazz/Rock/Funk B3, Pipe Diapason, Full Organ)",
        "category": "5 - ORGANS",
        "published_size": 35281761,
        "published_sha256": "2d6f220e4d9b37457482e125ede8c02d0a277a1d98008464d0014f653a5d3c5a",
        "asset_files": [
            "soundbank/2_-_SCAN_B3.numares",
            "soundbank/3_-_JAZZ_B3.numares",
            "soundbank/4_-_ROCK_B3.numares",
            "soundbank/5_-_FUNK_B3.numares",
            "soundbank/6_-_SCAN_PERC_B3.numares",
            "soundbank/7_-_POP_MID_SET.numares",
            "soundbank/8_-_MID_VIB_SET.numares",
            "soundbank/9_-_FULL_SET_B3.numares",
            "soundbank/10_-_FULL_VIB_SET.numares",
            "soundbank/11_-_SILK_SETTING.numares",
            "soundbank/12_-_EL_ORGAN_1.numares",
            "soundbank/13_-_EL_ORGAN_2.numares",
            "soundbank/14_-_VINT_PERC_1.numares",
            "soundbank/15_-_VINT_PERC_2.numares",
            "soundbank/16_-_FM_ORGAN_1.numares",
            "soundbank/17_-_FM_ORGAN_2.numares",
            "soundbank/18-_PIPE_DIAPASON.numares",
            "soundbank/19_-_PIPE_PLENUM.numares",
            "soundbank/20_-_FULL_ORGAN.numares",
        ],
    },
    {
        "id": "pack_bells_bass",
        "name": "Fantasia Bells & Synth Bass",
        "description": "Fantasia Bells, Sub Moog, Juno 80s, Reese, FM Solid Pluck",
        "category": "SF2",
        "published_size": 66907824,
        "published_sha256": "d9459e2e8b9b07a43fb8432b1ac056cd2b3080eabd38ee9cfd17fa2136ec6d3b",
        "asset_files": [
            "soundbank/Fantasia_Bells.sf2",
            "soundbank/SynthBass_Pack.sf2",
        ],
    },
]

# 22 Audio Evolution SoundFonts (47 new timbres) organized into 11 modular packs
AE_PACK_DEFS = [
    {
        "id": "pack_nord_ambient_pad",
        "name": "Nord Red Ambient Pad",
        "description": "Pad ambiente estéreo do Worship Immersion (Zona 4)",
        "files": [
            {
                "sf2File": "Nord_Red_Ambient_Pad.sf2",
                "driveId": "1LVZKdHP39cAZuxn-dwCZF-1gQOReZaOT",
                "sizeBytes": 77427014,
                "sha256": "a37f625ea8c6d48fa5556928c6f40bb5a87cccd5b9f22a375af0315e73331325",
                "timbres": [
                    {
                        "lib_id": "Nord Red Ambient Pad.sf2/Red Ambient Pad",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Nord Ambient Pad",
                        "model_name": "Nord Red Ambient Pad",
                        "internal_preset": "Red Ambient Pad",
                        "image_path": "../soundimages/INSTR_PAD_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            }
        ],
    },
    {
        "id": "pack_ae_worship_pads",
        "name": "Worship Pads & Strings Extras",
        "description": "004 Warm Pad Pno, Warm Pad 2, Warm Paddings, Phaser Strings 2, Superstringz, PSR 500",
        "files": [
            {
                "sf2File": "004_Warm_Pad_Pno.sf2",
                "driveId": "1g7c4nJsvAGJvAgDJ86ZnKQ-1QVpWiebT",
                "sizeBytes": 13108776,
                "sha256": "10860d32302c77d12fec251cfeb8c4f61be8e9968cd6bb8484a7db1d50746322",
                "timbres": [
                    {
                        "lib_id": "004 Warm Pad Pno.sf2/A004 Warm Pad Pno",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Strings & Pad",
                        "model_name": "004 Warm Pad Pno",
                        "internal_preset": "A004 Warm Pad Pno",
                        "image_path": "../soundimages/INSTR_PAD_1.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "WARM_PAD_2.sf2",
                "driveId": "1q049yD8bkkYOdOsMTbQJaKpF9tx8elf3",
                "sizeBytes": 30056870,
                "sha256": "3706e358f41d6faabc7f4eb9d2dadb9e68176cbe9264cc591823b9f0e9dd8b3f",
                "timbres": [
                    {
                        "lib_id": "WARM PAD 2.sf2/WARM PAD",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Strings & Pad",
                        "model_name": "Warm Pad 2",
                        "internal_preset": "WARM PAD",
                        "image_path": "../soundimages/INSTR_PAD_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "Warm_Paddings_PD.sf2",
                "driveId": "1mvTYk9Ivz6PdWe5rUp8ld_Y-irAxtmQ1",
                "sizeBytes": 36882098,
                "sha256": "1f02557ffd578e2ad760561e69f70354becdd3f6e2f658ab2437315f47afa230",
                "timbres": [
                    {
                        "lib_id": "Warm Paddings PD.sf2/Warm Paddings PD",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Strings & Pad",
                        "model_name": "Warm Paddings PD",
                        "internal_preset": "Warm Paddings PD",
                        "image_path": "../soundimages/INSTR_PADS.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "Phaser_Strings_2_PD.sf2",
                "driveId": "10-GY7zHjNuCKYNQUNX_WwqmnVM_vFUTk",
                "sizeBytes": 36363158,
                "sha256": "a4e8409e484b0e669569f188dd7d2560888e21092bbcd3c1e00d0b3da0b42a73",
                "timbres": [
                    {
                        "lib_id": "Phaser Strings 2 PD.sf2/Phaser Strings 2 PD",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Strings & Pad",
                        "model_name": "Phaser Strings 2 PD",
                        "internal_preset": "Phaser Strings 2 PD",
                        "image_path": "../soundimages/INSTR_STRINGS_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "Superstringz_PD.sf2",
                "driveId": "19kbqnXqtCDUGP3ptFL69saZTBUhHXO7P",
                "sizeBytes": 36827290,
                "sha256": "978c4fd04c686ba8eb6dcca744b3a4fe297a76dddd1e137399f6d3f9754b4414",
                "timbres": [
                    {
                        "lib_id": "Superstringz PD.sf2/Superstringz PD",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Strings & Pad",
                        "model_name": "Superstringz PD",
                        "internal_preset": "Superstringz PD",
                        "image_path": "../soundimages/INSTR_STRINGS_4.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "Strings_PSR_500.sf2",
                "driveId": "1LwxPoR--EiCLsK9vDhu0PQOrRtsQRk6Y",
                "sizeBytes": 497170,
                "sha256": "88a54ab095bfc56d24d4397a2f6c53e8614edc66f4403f97790c08531a1de802",
                "timbres": [
                    {
                        "lib_id": "Strings PSR 500.sf2/Strings PSR500",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Strings & Pad",
                        "model_name": "Strings PSR 500",
                        "internal_preset": "Strings PSR500",
                        "image_path": "../soundimages/INSTR_STRINGS_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
        ],
    },
    {
        "id": "pack_ae_leads_violino",
        "name": "Leads Worship & Violino UVI",
        "description": "Analog Dream Lead, Lead Galileu (LiraKeys), Violino UVI",
        "files": [
            {
                "sf2File": "Analog_Dream_LD.sf2",
                "driveId": "16v7y-15kbwlBLqKgzkaAgZeyLsCGM-uj",
                "sizeBytes": 13174082,
                "sha256": "b77ac4512eae7f157ee664273330331a1e3dd9e408ac5ee92c7d9682fa1a7b25",
                "timbres": [
                    {
                        "lib_id": "Analog Dream LD.sf2/Analog Dream LD",
                        "category_key": "6 - SYNTH_BASS",
                        "category_name": "Synth Bass & Sub",
                        "zone_title": "Synth Lead",
                        "model_name": "Analog Dream Lead",
                        "internal_preset": "Analog Dream LD",
                        "image_path": "../soundimages/INSTR_SYNTH.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "lead_galileu.sf2",
                "driveId": "1Qy-7EzPXAnTehxBgYM9QgrzUNJOwCQMl",
                "sizeBytes": 74002122,
                "sha256": "e01d5dfe6ceda6240ea6fe482843e0a8752fcb8b5f23a6b12c43f54260c01f6a",
                "timbres": [
                    {
                        "lib_id": "lead galileu.sf2/LeadGalileuLirakeys",
                        "category_key": "6 - SYNTH_BASS",
                        "category_name": "Synth Bass & Sub",
                        "zone_title": "Synth Lead",
                        "model_name": "Lead Galileu",
                        "internal_preset": "LeadGalileuLirakeys",
                        "image_path": "../soundimages/INSTR_SYNTH.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "VIOLINO_UVI.sf2",
                "driveId": "11a80ZQ_3svm7aZEat2bArgIReAIjlN9O",
                "sizeBytes": 160738048,
                "sha256": "1b58f3695dbc96c21161e12917780cdded099c0ab4b20724bb70b61a1f724cbf",
                "timbres": [
                    {
                        "lib_id": "VIOLINO UVI.sf2/VIOLINO UVI",
                        "category_key": "4 - STRINGS_PADS",
                        "category_name": "Strings & Pads",
                        "zone_title": "Solo Violin",
                        "model_name": "Violino UVI",
                        "internal_preset": "VIOLINO UVI",
                        "image_path": "../soundimages/INSTR_STRINGS_4.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
        ],
    },
    {
        "id": "pack_ae_nord_grands",
        "name": "Nord & Steinway Grand Pianos",
        "description": "Nord Gran Elegance, Grand Lady Steinway, Nord Studio Grand",
        "files": [
            {
                "sf2File": "E-Nord_Gran_Elegance_1.sf2",
                "driveId": "19SxWGagnHqNQfTaYf0dIeJTINmN8MRlk",
                "sizeBytes": 156708198,
                "sha256": "4b7f689f3659ad79c6cb73936795f307453da0b77a2e0b90d4d94ce129a7b1e2",
                "timbres": [
                    {
                        "lib_id": "E- Nord Gran Elegance 1.sf2/Elegant S",
                        "category_key": "1 - A_PIANO",
                        "category_name": "Acoustic Pianos",
                        "zone_title": "Nord Grand",
                        "model_name": "Nord Gran Elegance",
                        "internal_preset": "Elegant S",
                        "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png",
                        "bank": 0,
                        "prog": 2,
                    }
                ],
            },
            {
                "sf2File": "Grand_Lady.sf2",
                "driveId": "1LC2Qhz3mKM3Dh8Ay1PRv3RPzPjS0Ari4",
                "sizeBytes": 107528704,
                "sha256": "9fabe343caf63aad688e32e1028418351cc4a31b4bb36a7a693af089300073e9",
                "timbres": [
                    {
                        "lib_id": "Grand Lady.sf2/GRAND LADY",
                        "category_key": "1 - A_PIANO",
                        "category_name": "Acoustic Pianos",
                        "zone_title": "Steinway Grand",
                        "model_name": "Grand Lady Steinway",
                        "internal_preset": "GRAND LADY",
                        "image_path": "../soundimages/INSTR_GRAND_PIANO_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "Nord_Studio_Grand.sf2",
                "driveId": "1USx5JnrlbWg7Wg2lusfDkkKFe7aWkjE_",
                "sizeBytes": 237076668,
                "sha256": "1519db04cbfabbef9a1c12a31ff1e55044442677fc9f06d08f39aef14fb9d683",
                "timbres": [
                    {
                        "lib_id": "Nord Studio Grand.sf2/NordStudioGrand",
                        "category_key": "1 - A_PIANO",
                        "category_name": "Acoustic Pianos",
                        "zone_title": "Nord Grand",
                        "model_name": "Nord Studio Grand",
                        "internal_preset": "NordStudioGrand",
                        "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png",
                        "bank": 0,
                        "prog": 1,
                    }
                ],
            },
        ],
    },
    {
        "id": "pack_ae_uprights",
        "name": "Nord & JF Black Uprights",
        "description": "Nord Black Upright, JF Black Upright Full",
        "files": [
            {
                "sf2File": "Nord_Black_Upright.sf2",
                "driveId": "1ADbiqqTxF-J2mF4J23Bdf5oJ1ej79Gs4",
                "sizeBytes": 216883142,
                "sha256": "bc3a2810fa9556eb53cccf90cbf77e5c3ae120ae9aa08cd31a6f5f9e4c90777c",
                "timbres": [
                    {
                        "lib_id": "Nord Black Upright.sf2/Black Upright",
                        "category_key": "1 - A_PIANO",
                        "category_name": "Acoustic Pianos",
                        "zone_title": "Black Upright",
                        "model_name": "Nord Black Upright",
                        "internal_preset": "Black Upright",
                        "image_path": "../soundimages/INSTR_UPRIGHT_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "JF_Black_Upright_full.sf2",
                "driveId": "1TqbtJW9IfgxtBJClhWhyOxYl2I0KItwr",
                "sizeBytes": 211572842,
                "sha256": "4b5a4a110c999835994dba7645ea28beb0e15963c237377fa132e4acd1ad45b7",
                "timbres": [
                    {
                        "lib_id": "JF Black Upright full.sf2/BlackUpright",
                        "category_key": "1 - A_PIANO",
                        "category_name": "Acoustic Pianos",
                        "zone_title": "Black Upright",
                        "model_name": "JF Black Upright",
                        "internal_preset": "BlackUpright",
                        "image_path": "../soundimages/INSTR_UPRIGHT_2.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
        ],
    },
    {
        "id": "pack_ae_rhodes_ballade",
        "name": "Ballade E-Piano & Rhodes Affair KA",
        "description": "Ballade E-Piano (Rhodes 80s), Rhodes Affair KA",
        "files": [
            {
                "sf2File": "Ballade_E_Piano.sf2",
                "driveId": "1aYdrGKVXRn8vH2o9XFHv9sSmuJ0gtLVF",
                "sizeBytes": 260420044,
                "sha256": "01203fb0314852662125bcc9c8fe23f42d64d66b0512a7f2000e061d4a24a0c3",
                "timbres": [
                    {
                        "lib_id": "Ballade E Piano.sf2/Ballade E Piano",
                        "category_key": "2 - E_PIANO",
                        "category_name": "Electric Pianos",
                        "zone_title": "Ballade Rhodes",
                        "model_name": "Ballade E-Piano",
                        "internal_preset": "Ballade E Piano",
                        "image_path": "../soundimages/INSTR_E_PIANO.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
            {
                "sf2File": "RHODES_AFFAIR_KA.sf2",
                "driveId": "1jmD9DXz8S9BShRUigGC-SgkjTZyriH3j",
                "sizeBytes": 236049920,
                "sha256": "907efa5286221963cab4d53ff2c53d065427ffcd3c40e721b831532a0daef68a",
                "timbres": [
                    {
                        "lib_id": "RHODES AFFAIR - KA.sf2/RHODES AFFAIR - KA",
                        "category_key": "2 - E_PIANO",
                        "category_name": "Electric Pianos",
                        "zone_title": "Electric Piano",
                        "model_name": "Rhodes Affair KA",
                        "internal_preset": "RHODES AFFAIR - KA",
                        "image_path": "../soundimages/INSTR_RHODES_1.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            },
        ],
    },
    {
        "id": "pack_ae_tchamba",
        "name": "Piano e Cordas Tchamba",
        "description": "Virtual Grand, Felling Steinway, Violins Harmonics/Legato, Violas, Strings & Cello",
        "files": [
            {
                "sf2File": "Piano_e_Cordas_Tchamba.sf2",
                "driveId": "1mAtRpUYFYyc4l5undPafVExWjeU58RD9",
                "sizeBytes": 792746174,
                "sha256": "d2c045321d0843cfbc33bc25980453a4e363f50f1975aa6994ca1753da77bac9",
                "timbres": [
                    {"lib_id": "Piano e Cordas Tchamba.sf2/Virtual Grand Piano", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Acoustic Piano", "model_name": "Tchamba Virtual Grand", "internal_preset": "Virtual Grand Piano", "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png", "bank": 1, "prog": 0},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/FELLING - Steinway", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Steinway Grand", "model_name": "Tchamba Felling Steinway", "internal_preset": "FELLING - Steinway", "image_path": "../soundimages/INSTR_GRAND_PIANO_2.png", "bank": 1, "prog": 1},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/Vlns Harmonics", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Orchestral Strings", "model_name": "Tchamba Violins Harmonics", "internal_preset": "Vlns Harmonics", "image_path": "../soundimages/INSTR_STRINGS_2.png", "bank": 1, "prog": 2},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/Vlns II Full leg LP", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Orchestral Strings", "model_name": "Tchamba Violins Legato", "internal_preset": "Vlns II Full leg LP", "image_path": "../soundimages/INSTR_STRINGS_4.png", "bank": 1, "prog": 3},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/Vlas Full Esp Sus", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Orchestral Strings", "model_name": "Tchamba Violas Espressivo", "internal_preset": "Vlas Full Esp Sus", "image_path": "../soundimages/INSTR_STRINGS_2.png", "bank": 1, "prog": 4},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/F SVL Sus Vib Soft", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Orchestral Strings", "model_name": "Tchamba Strings Soft Vib", "internal_preset": "F SVL Sus Vib Soft", "image_path": "../soundimages/INSTR_STRINGS_4.png", "bank": 1, "prog": 5},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/F SVC Leg Vib", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Orchestral Strings", "model_name": "Tchamba Strings Legato Vib", "internal_preset": "F SVC Leg Vib", "image_path": "../soundimages/INSTR_STRINGS_2.png", "bank": 1, "prog": 6},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/F 18V Exp", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Orchestral Strings", "model_name": "Tchamba 18 Violins Exp", "internal_preset": "F 18V Exp", "image_path": "../soundimages/INSTR_STRINGS_4.png", "bank": 1, "prog": 7},
                    {"lib_id": "Piano e Cordas Tchamba.sf2/Cello FC Leg LPG Sp", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Solo Cello", "model_name": "Tchamba Cello Legato", "internal_preset": "Cello FC Leg LPG Sp", "image_path": "../soundimages/INSTR_CELLOS.png", "bank": 1, "prog": 8},
                ],
            }
        ],
    },
    {
        "id": "pack_ae_white_grand",
        "name": "Nord White Grand Full 24C",
        "description": "Piano de cauda Nord White Grand Full 24 camadas",
        "files": [
            {
                "sf2File": "Nord_White_Grand_Full_24C.sf2",
                "driveId": "1Q7X8iti3VIguW_i6fP_h0Otqe5te4bhu",
                "sizeBytes": 830932522,
                "sha256": "d894b4df5ffd03fafda1298be5fb8cb0ee21fce84b50e27ac90db2e55c006eba",
                "timbres": [
                    {
                        "lib_id": "Nord White Grand Full 24C.sf2/White Grand Full 24",
                        "category_key": "1 - A_PIANO",
                        "category_name": "Acoustic Pianos",
                        "zone_title": "Nord White Grand",
                        "model_name": "Nord White Grand Full 24C",
                        "internal_preset": "White Grand Full 24",
                        "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png",
                        "bank": 0,
                        "prog": 0,
                    }
                ],
            }
        ],
    },
    {
        "id": "pack_ae_worship_igrejas",
        "name": "Banco Worship Igrejas",
        "description": "Nord Piano, Grand Lady D, Elegant S, Nord Rhodes, Galaxy DX, Pad Base, ShinyPad, AutoPad, LoFiPad, OrganPad",
        "files": [
            {
                "sf2File": "Worship_Igrejas.sf2",
                "driveId": "13YnyyiGQPKjGw_7kADkqhW5-UKvFGvKA",
                "sizeBytes": 922977744,
                "sha256": "1c310115a65b3924404ec3ef7f86849d13673b97c3525f3d727ab9fcb8c68535",
                "timbres": [
                    {"lib_id": "Worship Igrejas.sf2/NORD Piano", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Piano", "model_name": "Worship Nord Piano", "internal_preset": "NORD Piano", "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png", "bank": 0, "prog": 0},
                    {"lib_id": "Worship Igrejas.sf2/NORD Grand Lady D", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Grand Lady D", "model_name": "Worship Grand Lady D", "internal_preset": "NORD Grand Lady D", "image_path": "../soundimages/INSTR_GRAND_PIANO_2.png", "bank": 0, "prog": 1},
                    {"lib_id": "Worship Igrejas.sf2/Elegant S", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "Worship Elegant S", "internal_preset": "Elegant S", "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png", "bank": 0, "prog": 2},
                    {"lib_id": "Worship Igrejas.sf2/NORD - Rhodes", "category_key": "2 - E_PIANO", "category_name": "Electric Pianos", "zone_title": "Electric Piano", "model_name": "Worship Nord Rhodes", "internal_preset": "NORD - Rhodes", "image_path": "../soundimages/INSTR_RHODES_1.png", "bank": 0, "prog": 3},
                    {"lib_id": "Worship Igrejas.sf2/Galaxy DX", "category_key": "2 - E_PIANO", "category_name": "Electric Pianos", "zone_title": "FM Electric Piano", "model_name": "Worship Galaxy DX", "internal_preset": "Galaxy DX", "image_path": "../soundimages/INSTR_FM_PIANO.png", "bank": 0, "prog": 4},
                    {"lib_id": "Worship Igrejas.sf2/PAD BASE", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Worship Pad", "model_name": "Worship Pad Base", "internal_preset": "PAD BASE", "image_path": "../soundimages/INSTR_PAD_1.png", "bank": 0, "prog": 5},
                    {"lib_id": "Worship Igrejas.sf2/PAD - ShinyPad", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Worship Pad", "model_name": "Worship ShinyPad", "internal_preset": "PAD - ShinyPad", "image_path": "../soundimages/INSTR_PAD_2.png", "bank": 0, "prog": 6},
                    {"lib_id": "Worship Igrejas.sf2/PAD - AutoPad", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Worship Pad", "model_name": "Worship AutoPad", "internal_preset": "PAD - AutoPad", "image_path": "../soundimages/INSTR_PADS.png", "bank": 0, "prog": 7},
                    {"lib_id": "Worship Igrejas.sf2/PAD - LoFiPad", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Worship Pad", "model_name": "Worship LoFiPad", "internal_preset": "PAD - LoFiPad", "image_path": "../soundimages/INSTR_PAD_1.png", "bank": 0, "prog": 8},
                    {"lib_id": "Worship Igrejas.sf2/PAD - OrganPAD", "category_key": "4 - STRINGS_PADS", "category_name": "Strings & Pads", "zone_title": "Worship Pad", "model_name": "Worship OrganPad", "internal_preset": "PAD - OrganPAD", "image_path": "../soundimages/INSTR_HMND_ORGAN.png", "bank": 0, "prog": 9},
                ],
            }
        ],
    },
    {
        "id": "pack_ae_nord_eps",
        "name": "Pack Nord EPs (Ballad / Silver / EP8)",
        "description": "Nord Ballad EP1, Nord Ballad EP2, Nord EP Silver, Nord EP8",
        "files": [
            {
                "sf2File": "Pack_Nord_EPs.sf2",
                "driveId": "1iWDlqYHh7O9vQGWA3FtzyNX4utRDcTqO",
                "sizeBytes": 1005141092,
                "sha256": "ec054970db4ea90b8f30b4e50b2617c965393a7c3532b84cd9f4c77db51532ac",
                "timbres": [
                    {"lib_id": "Pack Nord EPs.sf2/Ballad EP1", "category_key": "2 - E_PIANO", "category_name": "Electric Pianos", "zone_title": "Electric Piano", "model_name": "Nord Ballad EP1", "internal_preset": "Ballad EP1", "image_path": "../soundimages/INSTR_E_PIANO.png", "bank": 0, "prog": 0},
                    {"lib_id": "Pack Nord EPs.sf2/Ballad EP2", "category_key": "2 - E_PIANO", "category_name": "Electric Pianos", "zone_title": "Electric Piano", "model_name": "Nord Ballad EP2", "internal_preset": "Ballad EP2", "image_path": "../soundimages/INSTR_RHODES_1.png", "bank": 0, "prog": 1},
                    {"lib_id": "Pack Nord EPs.sf2/EPSilver", "category_key": "2 - E_PIANO", "category_name": "Electric Pianos", "zone_title": "Electric Piano", "model_name": "Nord EP Silver", "internal_preset": "EPSilver", "image_path": "../soundimages/INSTR_E_PIANO.png", "bank": 0, "prog": 2},
                    {"lib_id": "Pack Nord EPs.sf2/EP8", "category_key": "2 - E_PIANO", "category_name": "Electric Pianos", "zone_title": "Electric Piano", "model_name": "Nord EP8", "internal_preset": "EP8", "image_path": "../soundimages/INSTR_FM_PIANO.png", "bank": 0, "prog": 3},
                ],
            }
        ],
    },
    {
        "id": "pack_ae_nord_stage3",
        "name": "Banco Nord Stage 3 (6 Grands)",
        "description": "Grand Imperial, White Grand, Italian Grand, Silver Grand, Grand Lady D, Royal Grand 3D",
        "files": [
            {
                "sf2File": "Nord_Stage_3.sf2",
                "driveId": "15SZG_kmLP_uzaD01HjLWM9EbnqJUwySs",
                "sizeBytes": 1685913698,
                "sha256": "b4277cbf24698d493bb8740ce5601843ba4b668e388c5639583a853f55f482ff",
                "timbres": [
                    {"lib_id": "Nord Stage 3.sf2/Grand Imperial - No", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "NS3 Grand Imperial", "internal_preset": "Grand Imperial - No", "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png", "bank": 0, "prog": 2},
                    {"lib_id": "Nord Stage 3.sf2/White Grand - Nord", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "NS3 White Grand", "internal_preset": "White Grand - Nord", "image_path": "../soundimages/INSTR_GRAND_PIANO_2.png", "bank": 0, "prog": 3},
                    {"lib_id": "Nord Stage 3.sf2/Italian Grand - Nor", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "NS3 Italian Grand", "internal_preset": "Italian Grand - Nor", "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png", "bank": 0, "prog": 4},
                    {"lib_id": "Nord Stage 3.sf2/Silver Grand - Nord", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "NS3 Silver Grand", "internal_preset": "Silver Grand - Nord", "image_path": "../soundimages/INSTR_GRAND_PIANO_2.png", "bank": 0, "prog": 5},
                    {"lib_id": "Nord Stage 3.sf2/Grand Lady D - Nord", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "NS3 Grand Lady D", "internal_preset": "Grand Lady D - Nord", "image_path": "../soundimages/INSTR_GRAND_PIANO_2.png", "bank": 0, "prog": 6},
                    {"lib_id": "Nord Stage 3.sf2/Royal Grand 3D - No", "category_key": "1 - A_PIANO", "category_name": "Acoustic Pianos", "zone_title": "Nord Grand", "model_name": "NS3 Royal Grand 3D", "internal_preset": "Royal Grand 3D - No", "image_path": "../soundimages/INSTR_GRAND_PIANO_1.png", "bank": 0, "prog": 7},
                ],
            }
        ],
    },
]


def decoded_sf2_name(asset_file: str) -> str:
    base = os.path.basename(asset_file)
    return base[:-8] + ".sf2" if base.endswith(".numares") else base


def decode_numares_if_needed(raw: bytes, asset_file: str) -> bytes:
    if asset_file.endswith(".numares"):
        tbl = bytes(i ^ 0x5A for i in range(256))
        out = raw.translate(tbl)
    else:
        out = raw
    assert out[:4] == b"RIFF" and out[8:12] == b"sfbk", f"Invalid SF2 after decode: {asset_file}"
    return out


def optimize_soundimages(zf: zipfile.ZipFile):
    os.makedirs(OUT_IMAGES_DIR, exist_ok=True)
    existing = [f for f in os.listdir(OUT_IMAGES_DIR) if f.lower().endswith(".png")]
    if len(existing) >= 26:
        return
    orig_total = 0
    opt_total = 0
    count = 0
    for info in zf.infolist():
        if not info.filename.startswith("assets/soundimages/") or not info.filename.lower().endswith(".png"):
            continue
        raw = zf.read(info.filename)
        orig_total += len(raw)
        im = Image.open(io.BytesIO(raw))
        w, h = im.size
        if w > 480:
            nh = max(1, round(h * 480 / w))
            im = im.resize((480, nh), Image.Resampling.LANCZOS)
        if im.mode == "RGBA":
            im_q = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        else:
            im_q = im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        out_path = os.path.join(OUT_IMAGES_DIR, os.path.basename(info.filename))
        im_q.save(out_path, format="PNG", optimize=True)
        opt_total += os.path.getsize(out_path)
        count += 1
    print(f"[OK] Optimized {count} soundimages: {orig_total/1048576:.2f} MB -> {opt_total/1048576:.2f} MB")


def update_catalog_and_presets(cat: dict) -> dict:
    timbres = list(cat.get("timbre_catalog", []))
    existing_ids = {t["lib_id"] for t in timbres}

    for pack in AE_PACK_DEFS:
        for f in pack["files"]:
            asset_file = "soundbank/" + f["sf2File"]
            for t in f["timbres"]:
                if t["lib_id"] in existing_ids:
                    continue
                entry = {
                    "lib_id": t["lib_id"],
                    "category_key": t["category_key"],
                    "category_name": t["category_name"],
                    "zone_title": t["zone_title"],
                    "model_name": t["model_name"],
                    "internal_preset": t["internal_preset"],
                    "image_path": t["image_path"],
                    "is_numares": False,
                    "bank": t["bank"],
                    "prog": t["prog"],
                    "asset_file": asset_file,
                }
                timbres.append(entry)
                existing_ids.add(t["lib_id"])

    cat["timbre_catalog"] = timbres

    # Map model display names in presets back to real Nord/Steinway lib_ids now available in catalog
    model_to_real_lib = {
        "Elegant S": ("E- Nord Gran Elegance 1.sf2/Elegant S", "Nord Gran Elegance"),
        "Nord Gran Elegance": ("E- Nord Gran Elegance 1.sf2/Elegant S", "Nord Gran Elegance"),
        "GRAND LADY": ("Grand Lady.sf2/GRAND LADY", "Grand Lady Steinway"),
        "Grand Lady Steinway": ("Grand Lady.sf2/GRAND LADY", "Grand Lady Steinway"),
        "Black Upright": ("Nord Black Upright.sf2/Black Upright", "Nord Black Upright"),
        "Nord Black Upright": ("Nord Black Upright.sf2/Black Upright", "Nord Black Upright"),
        "Ballade E Piano": ("Ballade E Piano.sf2/Ballade E Piano", "Ballade E-Piano"),
        "Ballade E-Piano": ("Ballade E Piano.sf2/Ballade E Piano", "Ballade E-Piano"),
        "Red Ambient Pad": ("Nord Red Ambient Pad.sf2/Red Ambient Pad", "Nord Red Ambient Pad"),
    }

    banks = cat.get("banks", {})
    for bname, progs in banks.items():
        for p in progs:
            libs = p.get("libs", [])
            models = p.get("zone_models", [])
            znames = p.get("zone_names", [])
            # Replace Zona 4 (Strings & Pad) in Worship Immersion with Nord Red Ambient Pad
            if p.get("name") == "Worship Immersion" and len(libs) >= 4:
                libs[3] = "Nord Red Ambient Pad.sf2/Red Ambient Pad"
                if len(models) >= 4:
                    models[3] = "Nord Red Ambient Pad"
                if len(znames) >= 4:
                    znames[3] = "Nord Ambient Pad"
            for z in range(min(len(libs), len(models))):
                m = models[z]
                if m in model_to_real_lib:
                    real_lib, clean_model = model_to_real_lib[m]
                    libs[z] = real_lib
                    models[z] = clean_model

    return cat


def main():
    build_zips = "--build-zips" in sys.argv
    if not os.path.isfile(BASE_APK):
        print(f"[ERROR] Missing {BASE_APK}. Reassemble base_pack first.", file=sys.stderr)
        sys.exit(1)

    with zipfile.ZipFile(BASE_APK, "r") as zf:
        cat = json.loads(zf.read("assets/mobile_catalog.json").decode("utf-8"))
        orig_timbres = list(cat.get("timbre_catalog", []))

        timbres_by_file = {}
        for t in orig_timbres:
            timbres_by_file.setdefault(t["asset_file"], []).append(t)

        optimize_soundimages(zf)

        core_lib_ids = []
        core_sf2_files = []
        for af in sorted(CORE_ASSET_FILES):
            core_sf2_files.append(decoded_sf2_name(af))
            for t in timbres_by_file.get(af, []):
                core_lib_ids.append(t["lib_id"])

        packs_out = [
            {
                "id": "core",
                "name": "Essencial (Embutido)",
                "description": "Model D 1983, EP-Mark I, SynthPad2, PURE B3",
                "bundled": True,
                "zipFile": "",
                "downloadUrl": "",
                "sizeBytes": 0,
                "sha256": "",
                "sf2Files": core_sf2_files,
                "timbreIds": core_lib_ids,
                "timbreCount": len(core_lib_ids),
            }
        ]

        # Place Nord Red Ambient Pad right after Core so Worship Immersion's pad is at the top
        def build_ae_pack_entry(ap):
            sf2_files = [f["sf2File"] for f in ap["files"]]
            lib_ids = [t["lib_id"] for f in ap["files"] for t in f["timbres"]]
            total_sz = sum(f["sizeBytes"] for f in ap["files"])
            direct_files = [
                {
                    "sf2File": f["sf2File"],
                    "downloadUrl": drive_url(f["driveId"]),
                    "sizeBytes": f["sizeBytes"],
                    "sha256": f["sha256"],
                }
                for f in ap["files"]
            ]
            return {
                "id": ap["id"],
                "name": ap["name"],
                "description": ap["description"],
                "bundled": False,
                "zipFile": "",
                "downloadUrl": "",
                "sizeBytes": total_sz,
                "sha256": "",
                "sf2Files": sf2_files,
                "directFiles": direct_files,
                "timbreIds": lib_ids,
                "timbreCount": len(lib_ids),
            }

        packs_out.append(build_ae_pack_entry(AE_PACK_DEFS[0]))

        for p in PACK_DEFS:
            zip_name = f"{p['id']}.zip"
            sf2_names = [decoded_sf2_name(af) for af in p["asset_files"]]
            lib_ids = [t["lib_id"] for af in p["asset_files"] for t in timbres_by_file.get(af, [])]

            if build_zips:
                os.makedirs(OUT_PACKS_DIR, exist_ok=True)
                zip_path = os.path.join(OUT_PACKS_DIR, zip_name)
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
                    for af in p["asset_files"]:
                        raw = zf.read("assets/" + af)
                        sf2_bytes = decode_numares_if_needed(raw, af)
                        sf2_name = decoded_sf2_name(af)
                        zi = zipfile.ZipInfo(sf2_name)
                        zi.date_time = (2026, 1, 1, 0, 0, 0)
                        zi.compress_type = zipfile.ZIP_DEFLATED
                        zout.writestr(zi, sf2_bytes)
                sz = os.path.getsize(zip_path)
                h = hashlib.sha256()
                with open(zip_path, "rb") as f:
                    for chunk in iter(lambda: f.read(1048576), b""):
                        h.update(chunk)
                sha = h.hexdigest()
            else:
                sz = p["published_size"]
                sha = p["published_sha256"]

            packs_out.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "description": p["description"],
                    "bundled": False,
                    "zipFile": zip_name,
                    "downloadUrl": f"{BASE_URL}/{zip_name}",
                    "sizeBytes": sz,
                    "sha256": sha,
                    "sf2Files": sf2_names,
                    "timbreIds": lib_ids,
                    "timbreCount": len(lib_ids),
                }
            )

        for ap in AE_PACK_DEFS[1:]:
            packs_out.append(build_ae_pack_entry(ap))

        updated_cat = update_catalog_and_presets(cat)
        with open(OUT_CATALOG, "w", encoding="utf-8") as f:
            json.dump(updated_cat, f, indent=2, ensure_ascii=False)
            f.write("\n")

        manifest = {
            "version": 2,
            "repo": REPO,
            "releaseTag": PACKS_TAG,
            "coreAssetFiles": sorted(CORE_ASSET_FILES),
            "packs": packs_out,
        }
        with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")

        total_timbres = sum(pk["timbreCount"] for pk in packs_out)
        print(f"[SUCCESS] Wrote {OUT_CATALOG} ({len(updated_cat['timbre_catalog'])} timbres) and {OUT_MANIFEST} ({len(packs_out)} packs, {total_timbres} timbres)")


if __name__ == "__main__":
    main()

import os

MOCK_FOLDER = "test_data"
DEFAULT_MODEL = "htdemucs_6s"
STEM_ORDER = ["vocals", "guitar", "piano", "drums", "bass", "other"]
DEFAULT_INCLUDE = ["vocals", "drums", "bass", "piano", "other"]
DEFAULT_SR = 44100
DEFAULT_STICK_PATH = os.path.join("assets", "drumstick_sound.mp3")
TEMP_FILE = "trimmed_temp.wav"

per_include = {}
per_player = {}
per_start = {}
per_end = {}
per_silence_btn = {}
per_gain = {}
per_gain_btn = {}
per_reset_btn = {}


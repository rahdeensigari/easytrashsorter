# EZtrash

A self-sorting trash can for the InVenture Prize. A camera on a Raspberry Pi looks at each item, a model
trained on the Pi says what the item is (a can, a plastic bottle, a battery...), and a city's rules decide
which bin it goes in: recycling, trash, or special (hazardous or drop-off items). A servo tips the item
into that bin. A website on the Pi lets anyone switch cities or write their own rules.

The two halves are separate on purpose:

```
camera photo -> model: "what is it?" -> plastic_bottle -> rules: "where does it go here?" -> recycling -> servo
                 (model_local.npz)                         (rulebook.json)
```

So the same can works in any city: only the rules change, the model stays the same.

## What's in this folder

The folders match where the files go on the Pi.

| Folder | Goes to on the Pi | What it is |
|---|---|---|
| `Downloads/` | `~/Downloads` | All the code, the city presets, the current rules and the trained model |
| `Desktop/` | `~/Desktop` | `start.sh` (the EZtrash control panel) and `Sorter.desktop` (double-click icon) |
| `icons/` | `~/.icons` | `eztrash.png`, the picture for the desktop icon |
| `logo/` | not needed on the Pi | The logo as SVG (two colors) and PNG |
| `github-journal/` | the GitHub repo | Journal entries |

The training photos are in a separate zip (`EZtrash-Downloads-training-photos.zip`, 44 MB) because they're big.

### The code (`Downloads/`)

| File | What it does |
|---|---|
| `sorter.py` | Runs the can: camera, model, rules, servo. Logs every item to `sort_log.csv`. |
| `app.py` | The EZtrash website: pick a city, write rules, EZscan a rules document, see what goes where. |
| `rulebook.py` | The rules engine: item types, safe defaults, saving/loading rules, the rule writer's parser, EZscan's document reader. Used by both `app.py` and `sorter.py`. |
| `localmodel.py` | Loads the trained model for `sorter.py`. |
| `recognize.py` | Train the model on photo folders, test it on photos, or watch the camera live. |
| `train_local.py` | Another trainer, aware of the rule item types (warns about folder names it doesn't know). |
| `organize_photos.py` | Sorts a pile of photos into folders using the trained model (copies, never moves). |
| `collect.py` | Takes labeled photos with the Pi camera, for adding your own training photos. |
| `test_claude.py` | Optional: tests the Claude backup in `sorter.py` (needs an API key; nothing else does). |
| `setup_pi.sh` | One-time setup: installs packages and makes the Python environment `~/sorter-env`. |
| `run_app.sh` | Starts the website (`--public` also makes a public link with cloudflared). |
| `run_sorter.sh` | Starts the sorter (frees the camera first, picks the model automatically). |
| `mobilenetv2-7.onnx` | The image network the model is built on (MobileNetV2, 14 MB). |
| `model_local.npz` | The trained model (see "The model" below). |
| `rulebook.json` | The rules the can is using right now (Marietta, GA). |
| `rulebooks/` | Saved rules. |
| `presets/` | Ready-made rules for 41 US cities + 2 "typical US" templates, each from the city's official page. |
| `build_items.py`, `eval_items.py`, `make_sheets.py` | Helper tools used while building the dataset: build an item-type photo set, measure accuracy (optionally per bin for a city), and make contact sheets of photos for checking labels by eye. |

## Set up a Pi

Raspberry Pi OS 64-bit, with the camera and servo connected.

```
cd ~/Downloads
bash setup_pi.sh          # one time; press Enter to skip the API key (it's optional)
chmod +x ~/Desktop/start.sh ~/Desktop/Sorter.desktop
~/Desktop/start.sh        # or double-click the EZtrash icon
```

In the control panel, press a number:

1. Rules app on your Wi-Fi (the website prints its address and access code)
2. Rules app + a public link (needs `cloudflared`)
3. Trash sorter
4. Train the model on a photo folder
5. Camera check (shows what the model sees, live)

Esc stops what's running and closes the panel. Ctrl+C is turned off inside the panel so it can be used for copying.

## The model

`model_local.npz` was trained on the TrashNet photos, hand-sorted by object type (2,216 photos, 8 types):
aluminum_steel_can, cardboard, glass, other_trash, paper, plastic_bag, plastic_bottle, plastic_container.
On photos it never trained on (from the same collection) it was right 80.5% of the time. Plastic bags are
weak (25%) because there are only 22 bag photos. Real accuracy on our camera will be lower until we add our
own photos:

```
python3 collect.py plastic_bag          # take photos of bags on the platform
python3 recognize.py train trashnet_sorted my_photos
```

Folder names must be item types from `rulebook.py` (or `empty`, for the empty platform). Item types the model
hasn't learned yet (batteries, light bulbs, cups...) need our own photos.

## Rules

Each city's rules are a JSON file: for every item type, which bin (`recycling`, `trash`, `special`) and an
optional tip (`dropoff` or `hazardous`) shown on the screen. Anything a city doesn't mention gets a safe
default: trash for ordinary items, special for dangerous ones. The easiest way to make or change rules is the
website's rule writer:

```
recycling: cans, plastic bottles, cardboard, paper, newspaper
trash: plastic bags, plastic cups, everything else
special, hazardous: batteries, light bulbs, medicine, needles, spray cans
special, drop-off: electronics, cables, glass
```

To add a city preset, write its rules in the website, save them, and copy the file from `rulebooks/` into
`presets/`. Please base presets on the city's official recycling page and check every row.

## Known limits

- Nothing here has been run end to end on the real can yet (camera + servo + bins together).
- Model accuracy on our own camera is unknown until we test it; expect it to be lower than 80%.
- Hazardous items can be missed by the model; the safe defaults send unknown items to trash.
- City presets were taken from official pages in November 2026. Rules change, so check before a demo.
- EZscan reads documents with simple word matching (no AI). It works best on a city's "what can I
  recycle" list. Always check the rows it fills in.

## Credits

Training photos: TrashNet by Gary Thung and Mindy Yang (github.com/garythung/trashnet), re-sorted by object
type for this project. Image network: MobileNetV2 (ONNX model zoo). City rules: each city's official
recycling page (listed in each preset's `source_name`).

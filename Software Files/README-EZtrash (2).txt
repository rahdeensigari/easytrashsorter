EZtrash: the files that go in your Downloads folder (~/Downloads)
Unzip:   unzip -o EZtrash-Downloads.zip -d ~/Downloads

app.py               the EZtrash website (rules, city picker, EZscan)
rulebook.py          rules engine (used by app.py and sorter.py)
sorter.py            runs the trash can: camera, model, servo
localmodel.py        on-device model (used by sorter.py)
recognize.py         train / test the model (start.sh options 4 and 5)
train_local.py       another way to train the model (for sorter.py)
organize_photos.py   sort a pile of photos into folders with your model
collect.py           take labeled photos with the camera
test_claude.py       optional test of the Claude backup (needs an API key)
setup_pi.sh          one-time setup of the Python environment
run_app.sh           starts the website (used by start.sh)
run_sorter.sh        starts the sorter (used by start.sh)
mobilenetv2-7.onnx   the image network the model is built on
presets/             the 41 city rule presets + 2 templates

rulebook.json        the rules the can is using now (Marietta, GA)
rulebooks/           saved rules
model_local.npz      trained model (8 item types, hand-sorted TrashNet photos)
build_items.py, eval_items.py, make_sheets.py   helper tools used to build and check the dataset

On a Pi that already has its own rules and model, keep them by skipping those files:
  unzip -o EZtrash-Downloads.zip -x rulebook.json 'rulebooks/*' model_local.npz -d ~/Downloads

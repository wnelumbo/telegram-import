import json
import pathlib

# Folder with json files
FOLDER = pathlib.Path("YOUR_PATH")  # for example, FOLDER = pathlib.Path("C:/Users/YourName/ChatExport_2025-05-23")
OUTFILE = FOLDER / "result.json"

# List of files in order
files = [FOLDER / "messages.json"] + [FOLDER / f"messages{i}.json" for i in range(2, 132)]

all_messages = []
meta = None

for idx, file in enumerate(files):
    if not file.exists():
        print(f"Missed: {file}")
        continue
    with open(file, encoding="utf-8") as f:
        data = json.load(f)
        # Support for both formats (list or object with key messages)
        if isinstance(data, dict) and "messages" in data:
            msgs = data["messages"]
            # Copy the "header" (metadata) only from the first file
            if meta is None:
                meta = {k: v for k, v in data.items() if k != "messages"}
        elif isinstance(data, list):
            msgs = data
        else:
            print(f"Unknown file format: {file}")
            continue
        all_messages.extend(msgs)

# Combine everything into a single object with metadata and messages
if meta is None:
    meta = {}
result = meta.copy()
result["messages"] = all_messages

with open(OUTFILE, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ Merging completed! Total messages: {len(all_messages)}")
print(f"Final file: {OUTFILE}")

from timeliner_reader import fetch_and_parse_timeliner
entries = fetch_and_parse_timeliner()
for e in entries:
    print(f"Subtheme: {e.colour_subtheme}, Priority: {e.priority}")

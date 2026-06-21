import sys
from timeliner_reader import fetch_and_parse_timeliner

def main():
    print("Fetching from Notion...")
    entries = fetch_and_parse_timeliner(force_live=True)
    print("\nOrder in Notion:")
    for i, e in enumerate(entries):
        scope_key = e.subtheme_key() if hasattr(e, 'subtheme_key') else f"{e.project}::::{e.colour_subtheme}"
        print(f"{i+1}. Project: {e.project}, SubProject: {e.subproject}, Subtheme: {e.colour_subtheme}")

if __name__ == '__main__':
    main()

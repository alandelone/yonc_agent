import sys
sys.stdout.reconfigure(encoding='utf-8')

from timeliner_reader import _split_leading_label

raw = "Thesis thesis writing"
lead, rest = _split_leading_label(raw)
resolved_project = "Thesis"

print("Initial:")
print(f"raw={raw!r}, lead={lead!r}, rest={rest!r}")

if resolved_project and lead and rest and lead.lower() == resolved_project.lower():
    subtheme = rest
    print("After elif strip:", subtheme)

while resolved_project:
    l2, r2 = _split_leading_label(subtheme)
    print(f"While loop: l2={l2!r}, r2={r2!r}")
    if l2 and r2 and l2.lower() == resolved_project.lower() and " " in r2:
        subtheme = r2
        print("While stripped:", subtheme)
    else:
        print("While broke out")
        break

print(f"Final Reader subtheme: {subtheme!r}")

print("\n--- Sync ---")
badge_label = "Thesis"
task_label = subtheme
colour_sub = subtheme

colour_sub_starts_with_badge = bool(
    badge_label and colour_sub
    and colour_sub.lower().startswith(badge_label.lower())
)

print(f"Starts with badge? {colour_sub_starts_with_badge}")
if badge_label and not colour_sub_starts_with_badge:
    import re
    match = re.match(r'^([^\w]*)' + re.escape(badge_label) + r'\s+(.*)$', task_label, flags=re.IGNORECASE)
    if match:
        task_label = (match.group(1) + match.group(2)).strip()

print(f"Final task label to write: {task_label!r}")
print(f"Written text will look like: 🟢**`{badge_label}`** {task_label} Takes ...")

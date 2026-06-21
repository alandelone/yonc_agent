import re
import sys
sys.stdout.reconfigure(encoding='utf-8')

task_label = "🏭 SolarMan Apparatus Learning"
badge_label = "SolarMan"

match = re.match(r'^([^\w]*)' + re.escape(badge_label) + r'\s+(.*)$', task_label, flags=re.IGNORECASE)
if match:
    task_label = (match.group(1) + match.group(2)).strip()
    
print("New task_label:", task_label)

task_label2 = "Thesis Phd Logic"
badge_label2 = "Thesis"

match2 = re.match(r'^([^\w]*)' + re.escape(badge_label2) + r'\s+(.*)$', task_label2, flags=re.IGNORECASE)
if match2:
    task_label2 = (match2.group(1) + match2.group(2)).strip()

print("New task_label2:", task_label2)

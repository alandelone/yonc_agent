import json
d=json.load(open('temp_out_solarman.json', encoding='utf-8'))
daq=[t for t in d if 'DAQ' in t.get('title', '')][0]
state_by_id={str(t.get('notion_block_id')): t for t in d}
parent_titles=[]
p=daq.get('parent_id')
print('Initial p:', p)
c=0
while p and c<3:
    pt=state_by_id.get(str(p))
    print('Found pt:', bool(pt))
    if pt:
        parent_titles.append(str(pt.get('original_notion_title', '')))
        p=pt.get('parent_id')
        c+=1
    else:
        break
print('Parent Titles:', [t.encode('ascii', 'ignore').decode() for t in parent_titles])

import sys, importlib.util
from zoneinfo import ZoneInfo
spec=importlib.util.spec_from_file_location("cost",__import__("pathlib").Path(__file__).parents[1] / "custom_components/salzburgnetz/cost.py"); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
tz=ZoneInfo("Europe/Vienna")
sep1=c.valid_from_timestamp("2026-09-01",0,tz); oct1=c.valid_from_timestamp("2026-10-01",0,tz)
assert c.valid_from_timestamp(None,123,tz)==123 and c.valid_from_timestamp("bad",5,tz)==5
H=3600
hours={int(sep1-2*H):1.0,int(sep1-H):1.0,int(sep1):2.0,int(sep1+H):1.0,int(oct1):3.0}
tl,ch=c.add_price([],sep1,0.4); assert ch==sep1
tl2,ch2=c.add_price(tl,sep1,0.4); assert ch2 is None and tl2==tl
tl3,ch3=c.add_price(tl,oct1,0.4); assert ch3 is None  # same price continues
tl4,ch4=c.add_price(tl,oct1,0.5); assert ch4==oct1 and len(tl4)==2
rows=c.cost_rows(hours,tl4,0)
assert [r[0] for r in rows]==[int(sep1),int(sep1+H),int(oct1)], rows
assert rows[0][1]==0.8 and rows[1][2]==1.2 and rows[2][1]==1.5 and rows[2][2]==2.7, rows
part=c.cost_rows(hours,tl4,oct1); assert part==[rows[2]]
tl5,ch5=c.add_price(tl4,sep1,0.3); assert ch5==sep1 and tl5==[[sep1,0.3]]  # back-dated correction replaces later
print("ok",rows)

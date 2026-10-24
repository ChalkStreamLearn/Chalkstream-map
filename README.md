# Plot / Yard GeoJSON Digitizer

Esri satellite map ပေါ်မှာ plot/yard polygon များ ဆွဲပြီး `plot_no` နှင့် `yard_no` ဖြည့်ကာ GeoJSON, GeoPackage နှင့် Shapefile ZIP အဖြစ် download လုပ်နိုင်သော Streamlit app ဖြစ်သည်။

## Install

```bash
cd ~/plot-mapper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

Browser တွင် ပုံမှန်အားဖြင့် `http://localhost:8501` ကိုဖွင့်ပါ။

## အသုံးပြုပုံ

1. Sidebar တွင် map center နှင့် zoom သတ်မှတ်ပါ။ Zoom ကို 12 မှ 23 အထိ တိုးချဲ့ထားပြီး ပိုနီးကပ်စွာ ကြည့်နိုင်သည်။
2. Satellite map toolbar မှ polygon သို့မဟုတ် rectangle ကို ရွေးပြီး plot ကို ဆွဲပါ။
3. အောက်ရှိ ဇယားတွင် `plot_no` နှင့် `yard_no` ဖြည့်ပါ။
4. လိုအပ်လျှင် polygon တစ်ခုကိုရွေးပြီး ဖျက်ပါ။
5. GeoJSON, GeoPackage သို့မဟုတ် Shapefile ZIP ကို download လုပ်ပါ။

Output CRS သည် EPSG:4326 (WGS 84) ဖြစ်သည်။ Esri imagery သုံးရာတွင် map attribution ကို မဖျက်ပါနှင့်။

Map Layer Control မှ `Satellite imagery` နှင့် `Vector map — OpenStreetMap` ကို ပြောင်းကြည့်နိုင်သည်။ Polygon များကို app folder အတွင်း `shared_polygons.json` တွင် သိမ်းထားပြီး browser tab များသည် ၃ စက္ကန့်တစ်ကြိမ် shared state ကို ပြန်ဖတ်သောကြောင့် tab တစ်ခုတွင် ဆွဲထားသော polygon ကို အခြား tab များတွင်လည်း အလိုအလျောက်မြင်ရသည်။

## Offline mode

Sidebar မှ `Offline mode` ကို ဖွင့်ထားလျှင် online Esri/OSM tile မခေါ်ပါ။ `Satellite image (PNG/JPG)` တွင် download လုပ်ထားသော satellite image ကို upload လုပ်ပြီး `Satellite image bounds` တွင် `xmin/ymin/xmax/ymax` ဖြည့်ပါ။ `Local vector data` တွင် GeoJSON၊ GeoPackage သို့မဟုတ် Shapefile ZIP upload လုပ်နိုင်ပါသည်။ Upload လုပ်ထားသော local satellite/vector layer များသည် offline map ပေါ်တွင် ပြသပြီး ထိုအပေါ်တွင် polygon ဆွဲနိုင်ပါသည်။

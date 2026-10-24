# GitHub manual upload နှင့် Streamlit Cloud deploy

## ၁။ GitHub မှာ repository ဖန်တီးပါ

1. GitHub.com ကို iPad browser ဖြင့်ဖွင့်ပြီး login ဝင်ပါ။
2. **New repository** ကိုနှိပ်ပါ။
3. Repository name ကို `plot-mapper` ဟုထည့်ပါ။
4. Private သို့မဟုတ် Public ရွေးပြီး **Create repository** ကိုနှိပ်ပါ။

## ၂။ ဖိုင်များ upload လုပ်ပါ

Repository ထဲတွင် **Add file → Upload files** ကိုရွေးပြီး ZIP ထဲမှ အောက်ပါဖိုင်များကို တစ်ဖိုင်ချင်း upload လုပ်ပါ။

- `app.py`
- `requirements.txt`
- `README.md`
- `DEPLOY_STREAMLIT.md`

`.venv` folder ကို မတင်ပါနှင့်။ `shared_polygons.json` မရှိသေးလျှင် ပြဿနာမရှိပါ၊ app က အလိုအလျောက်ဖန်တီးပါမည်။

## ၃။ Streamlit Cloud မှာ run ပါ

1. `share.streamlit.io` ကိုဖွင့်ပါ။
2. **Deploy an app → Create app** ကိုရွေးပါ။
3. သင်တင်ထားသော GitHub repository ကိုရွေးပါ။
4. Branch ကို `main` ထားပါ။
5. Main file path ကို `app.py` ထားပါ။
6. **Deploy** ကိုနှိပ်ပါ။

Deploy ပြီးလျှင် Streamlit URL ကို iPad Safari/Chrome မှဖွင့်ပြီး app သုံးနိုင်ပါသည်။

## Offline mode သတိပြုရန်

Streamlit Cloud တွင် Offline mode ကိုအသုံးပြုရန် satellite PNG/JPG နှင့် vector GeoJSON/GPKG/Shapefile ZIP ကို app sidebar မှ ပြန် upload လုပ်ရပါမည်။ Cloud app ၏ local filesystem သည် အမြဲတမ်းသိမ်းဆည်းရန်မဟုတ်သောကြောင့် app restart/redeploy ဖြစ်လျှင် upload data ပြန်ထည့်ရန်လိုနိုင်ပါသည်။

`shared_polygons.json` သည် app instance အတွင်း tab များအတွက် shared ဖြစ်သော်လည်း permanent database မဟုတ်ပါ။ အမြဲတမ်း data သိမ်းရန် နောက်ပိုင်းတွင် Google Drive, Supabase သို့မဟုတ် PostgreSQL ချိတ်ဆက်နိုင်ပါသည်။

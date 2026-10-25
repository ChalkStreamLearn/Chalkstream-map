import base64
import hashlib
import io
import json
import re
import tempfile
import uuid
import zipfile
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from shapely.affinity import translate
from shapely.geometry import mapping, shape
from streamlit_folium import st_folium


st.set_page_config(page_title="Plot / Yard Map Digitizer", layout="wide")
st.markdown(
    """
    <style>
    .block-container { padding-top: .7rem; padding-bottom: 1.2rem; }
    div[data-testid="stButton"] button { min-height: 2.65rem; }
    @media (max-width: 640px) {
      .block-container { padding-left: .7rem; padding-right: .7rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Plot / Yard မြေပုံရေးဆွဲခြင်း")
st.caption(
    "Polygon ဆွဲပါ၊ Plot/Yard အချက်အလက်ဖြည့်ပါ၊ လိုအပ်လျှင် မြှားခလုတ် ၄ ခုဖြင့် "
    "ရွှေ့ပြီး GeoJSON၊ GeoPackage သို့မဟုတ် Shapefile ထုတ်ပါ။"
)

# Polygon data is saved beside app.py on the computer running Streamlit.
LOCAL_DATA_PATH = Path(__file__).resolve().with_name("shared_polygons.json")


def load_features():
    try:
        if LOCAL_DATA_PATH.exists():
            data = json.loads(LOCAL_DATA_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        st.warning("Local polygon file ကို ဖတ်မရပါ။ Polygon အသစ်များကို စတင်နိုင်ပါသည်။")
    return []


def save_features(features):
    """Write atomically so an interrupted save does not corrupt the local file."""
    LOCAL_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = LOCAL_DATA_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(features, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(LOCAL_DATA_PATH)


def normalize_feature(item):
    if not isinstance(item, dict):
        return None
    if item.get("type") == "Feature":
        feature = item
    elif item.get("type") in ("Polygon", "MultiPolygon"):
        feature = {"type": "Feature", "properties": {}, "geometry": item}
    else:
        return None
    geometry = feature.get("geometry") or {}
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    properties = feature.get("properties") or {}
    properties.setdefault("feature_id", str(uuid.uuid4()))
    properties.setdefault("plot_no", "")
    properties.setdefault("yard_no", "")
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def geometry_key(feature):
    return json.dumps(feature["geometry"], sort_keys=True, separators=(",", ":"))


def shift_feature(feature, direction, meters):
    """Shift one WGS84 feature in its local UTM CRS by the requested metres."""
    geometry = shape(feature["geometry"])
    source = gpd.GeoSeries([geometry], crs="EPSG:4326")
    local_crs = source.estimate_utm_crs()
    if local_crs is None:
        raise ValueError("ဒီတည်နေရာအတွက် local UTM CRS ကို သတ်မှတ်မရပါ။")
    local_geometry = source.to_crs(local_crs).iloc[0]
    offsets = {
        "north": (0.0, meters),
        "south": (0.0, -meters),
        "east": (meters, 0.0),
        "west": (-meters, 0.0),
    }
    dx, dy = offsets[direction]
    moved_local = translate(local_geometry, xoff=dx, yoff=dy)
    moved_wgs84 = gpd.GeoSeries([moved_local], crs=local_crs).to_crs("EPSG:4326").iloc[0]
    feature["geometry"] = mapping(moved_wgs84)


def read_uploaded_vector(uploaded_file):
    """Read GeoJSON/GPKG/Shapefile ZIP and return a WGS84 GeoJSON collection."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / Path(uploaded_file.name).name
        source_path.write_bytes(uploaded_file.getvalue())
        read_path = source_path
        if suffix == ".zip":
            extract_path = temp_path / "unzipped"
            extract_path.mkdir()
            with zipfile.ZipFile(source_path) as archive:
                archive.extractall(extract_path)
            shapefiles = list(extract_path.rglob("*.shp"))
            if not shapefiles:
                raise ValueError("ZIP ထဲတွင် .shp ဖိုင်မတွေ့ပါ။")
            read_path = shapefiles[0]
        gdf = gpd.read_file(read_path)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        else:
            gdf = gdf.to_crs("EPSG:4326")
        return json.loads(gdf.to_json(drop_id=True, ensure_ascii=False))


def image_data_uri(uploaded_file):
    mime = uploaded_file.type or "image/jpeg"
    encoded = base64.b64encode(uploaded_file.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


if "features" not in st.session_state:
    st.session_state.features = [
        feature for item in load_features()
        if (feature := normalize_feature(item)) is not None
    ]
if "map_revision" not in st.session_state:
    st.session_state.map_revision = 0

with st.sidebar:
    st.header("မြေပုံတည်နေရာ")
    center_lat = st.number_input("Center latitude", value=0.0, format="%.6f")
    center_lon = st.number_input("Center longitude", value=0.0, format="%.6f")
    zoom_level = st.slider("Zoom", min_value=2, max_value=23, value=2)

    offline_mode = st.checkbox(
        "Offline mode",
        value=False,
        help="ဖွင့်ထားလျှင် Esri/OSM online tiles မခေါ်ပါ။",
    )
    st.caption("Offline အတွက် local layer ထည့်ရန်")
    satellite_upload = st.file_uploader(
        "Satellite image (PNG/JPG)",
        type=["png", "jpg", "jpeg"],
        key="offline_satellite_upload",
    )
    with st.expander("Satellite image bounds", expanded=False):
        image_west = st.number_input("West / xmin", value=-180.0, format="%.6f")
        image_south = st.number_input("South / ymin", value=-90.0, format="%.6f")
        image_east = st.number_input("East / xmax", value=180.0, format="%.6f")
        image_north = st.number_input("North / ymax", value=90.0, format="%.6f")
    vector_upload = st.file_uploader(
        "Local vector data (GeoJSON/GPKG/Shapefile ZIP)",
        type=["geojson", "json", "gpkg", "zip"],
        key="offline_vector_upload",
    )

    if satellite_upload is not None:
        sat_hash = hashlib.md5(satellite_upload.getvalue()).hexdigest()
        if st.session_state.get("satellite_hash") != sat_hash:
            st.session_state.satellite_hash = sat_hash
            st.session_state.local_satellite = {
                "image": image_data_uri(satellite_upload),
                "bounds": [[image_south, image_west], [image_north, image_east]],
            }
        elif st.session_state.get("local_satellite"):
            st.session_state.local_satellite["bounds"] = [
                [image_south, image_west], [image_north, image_east]
            ]

    if vector_upload is not None:
        vector_hash = hashlib.md5(vector_upload.getvalue()).hexdigest()
        if st.session_state.get("vector_hash") != vector_hash:
            try:
                st.session_state.local_vector = read_uploaded_vector(vector_upload)
                st.session_state.vector_hash = vector_hash
                st.success("Local vector layer ထည့်ပြီးပါပြီ။")
            except Exception as exc:
                st.error(f"Vector ဖိုင်ဖတ်မရပါ: {exc}")

    if st.button("Polygon အားလုံး ဖျက်ရန်", use_container_width=True):
        st.session_state.features = []
        save_features([])
        st.session_state.map_revision += 1
        st.rerun()

# Restore prior features and provide selectable movement controls.
features = st.session_state.features
if features:
    st.subheader("အကွက်ရွှေ့ရန်")

    def feature_label(index):
        props = features[index].get("properties", {})
        plot = props.get("plot_no") or f"Plot {index + 1}"
        yard = props.get("yard_no") or "Yard မသတ်မှတ်ရသေး"
        return f"{plot} — {yard}"

    choose_col, metres_col = st.columns([2, 1])
    with choose_col:
        selected_index = st.selectbox(
            "ရွှေ့မည့်အကွက်",
            options=list(range(len(features))),
            format_func=feature_label,
            key="movement_feature",
        )
    with metres_col:
        move_meters = st.number_input(
            "တစ်ချက်လျှင် ရွှေ့မည့်အကွာအဝေး (m)",
            min_value=0.1,
            max_value=10000.0,
            value=1.0,
            step=0.5,
        )

    top = st.columns([1, 1, 1])
    bottom = st.columns([1, 1, 1])
    move_north = top[1].button("↑ မြောက်", use_container_width=True, key="move_north")
    move_west = bottom[0].button("← အနောက်", use_container_width=True, key="move_west")
    move_south = bottom[1].button("↓ တောင်", use_container_width=True, key="move_south")
    move_east = bottom[2].button("အရှေ့ →", use_container_width=True, key="move_east")

    button_directions = [
        (move_north, "north"),
        (move_south, "south"),
        (move_east, "east"),
        (move_west, "west"),
    ]
    for pressed, direction in button_directions:
        if pressed:
            try:
                shift_feature(features[selected_index], direction, float(move_meters))
                save_features(features)
                st.session_state.map_revision += 1
                st.rerun()
            except Exception as exc:
                st.error(f"အကွက်ရွှေ့ရာတွင် အမှားဖြစ်နေပါသည်: {exc}")
    st.caption("မြှားတစ်ချက်နှိပ်တိုင်း ရွေးထားသော polygon ကို သတ်မှတ်မီတာအတိုင်း ရွှေ့ပါသည်။")

# Keep the current map view through edits and movements.
sidebar_view = (float(center_lat), float(center_lon), int(zoom_level))
if "map_view_center" not in st.session_state or st.session_state.get("_sidebar_view") != sidebar_view:
    st.session_state.map_view_center = sidebar_view[:2]
    st.session_state.map_view_zoom = sidebar_view[2]
st.session_state._sidebar_view = sidebar_view

map_obj = folium.Map(
    location=list(st.session_state.map_view_center),
    zoom_start=st.session_state.map_view_zoom,
    tiles=None,
    control_scale=True,
)
local_satellite = st.session_state.get("local_satellite")
local_vector = st.session_state.get("local_vector")
if offline_mode and not local_satellite and not local_vector:
    st.warning("Offline mode ဖွင့်ထားသော်လည်း local satellite/vector layer မရှိသေးပါ။")
if local_satellite:
    folium.raster_layers.ImageOverlay(
        image=local_satellite["image"],
        bounds=local_satellite["bounds"],
        opacity=1.0,
        interactive=False,
        cross_origin=False,
        zindex=1,
        name="Local satellite image",
        overlay=False,
        control=True,
    ).add_to(map_obj)
if not offline_mode:
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Online satellite imagery",
        overlay=False,
        control=True,
    ).add_to(map_obj)
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr="© OpenStreetMap contributors",
        name="Online vector map — OpenStreetMap",
        overlay=False,
        control=True,
    ).add_to(map_obj)
if local_vector:
    folium.GeoJson(
        local_vector,
        name="Local vector data",
        style_function=lambda _feature: {
            "color": "#1769aa", "weight": 2,
            "fillColor": "#4dabf7", "fillOpacity": 0.18,
        },
    ).add_to(map_obj)

for number, feature in enumerate(st.session_state.features, start=1):
    props = feature.get("properties") or {}
    label = f"Plot: {props.get('plot_no', '')} | Yard: {props.get('yard_no', '')}"
    folium.GeoJson(
        feature,
        name=f"Plot {number}",
        tooltip=label,
        style_function=lambda _feature: {
            "color": "#ff3333", "weight": 3,
            "fillColor": "#ff5555", "fillOpacity": 0.25,
        },
    ).add_to(map_obj)

Draw(
    draw_options={
        "polyline": False,
        "polygon": True,
        "rectangle": True,
        "circle": False,
        "circlemarker": False,
        "marker": False,
    },
    # Use the move controls below to edit existing geometry without losing local state.
    edit_options={"edit": False, "remove": False},
    export=False,
).add_to(map_obj)
folium.LayerControl().add_to(map_obj)

st.subheader("Satellite / Vector map")
st.caption("Toolbar မှ polygon သို့မဟုတ် rectangle ဆွဲပါ။ ဆွဲပြီးနောက် app က local JSON ဖိုင်သို့ အလိုအလျောက်သိမ်းပါသည်။")
map_result = st_folium(
    map_obj,
    height=560,
    use_container_width=True,
    returned_objects=["all_drawings", "center", "zoom"],
    key=f"plot_map_{st.session_state.map_revision}",
)
if map_result:
    current_center = map_result.get("center")
    if isinstance(current_center, dict) and current_center.get("lat") is not None and current_center.get("lng") is not None:
        st.session_state.map_view_center = (
            float(current_center["lat"]), float(current_center["lng"])
        )
    current_zoom = map_result.get("zoom")
    if current_zoom is not None:
        st.session_state.map_view_zoom = max(2, min(23, int(round(float(current_zoom)))))

# Import newly drawn polygons, avoiding duplicates already in local storage.
drawings = (map_result or {}).get("all_drawings") or []
known_geometries = {geometry_key(feature) for feature in st.session_state.features}
new_feature_added = False
for item in drawings:
    feature = normalize_feature(item)
    if feature is None:
        continue
    key = geometry_key(feature)
    if key in known_geometries:
        continue
    st.session_state.features.append(feature)
    known_geometries.add(key)
    new_feature_added = True
if new_feature_added:
    save_features(st.session_state.features)
    st.session_state.map_revision += 1
    st.rerun()

features = st.session_state.features
if not features:
    st.info("Polygon မရှိသေးပါ။ Map toolbar မှ polygon တစ်ခု အရင်ဆွဲပါ။")
    st.stop()

st.subheader("Plot / Yard အချက်အလက်")
rows = []
for index, feature in enumerate(features, start=1):
    props = feature.setdefault("properties", {})
    rows.append({
        "Feature": index,
        "plot_no": str(props.get("plot_no", "")),
        "yard_no": str(props.get("yard_no", "")),
    })
feature_ids = [
    str(feature.get("properties", {}).get("feature_id", index))
    for index, feature in enumerate(features)
]
edited_df = st.data_editor(
    pd.DataFrame(rows),
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    disabled=["Feature"],
    key="plot_attributes_" + "_".join(feature_ids),
    column_config={
        "Feature": st.column_config.NumberColumn("အကွက်", format="%d"),
        "plot_no": st.column_config.TextColumn("Plot number", help="ဥပမာ P-001"),
        "yard_no": st.column_config.TextColumn("Yard number", help="ဥပမာ Y-05"),
    },
)
attributes_changed = False
for index, row in edited_df.iterrows():
    props = features[index].setdefault("properties", {})
    plot_no = str(row["plot_no"])
    yard_no = str(row["yard_no"])
    if props.get("plot_no", "") != plot_no:
        props["plot_no"] = plot_no
        attributes_changed = True
    if props.get("yard_no", "") != yard_no:
        props["yard_no"] = yard_no
        attributes_changed = True
if attributes_changed:
    save_features(features)
    st.rerun()

st.subheader("အကွက်ဖျက်ရန်")
def feature_label(index):
    props = features[index].get("properties", {})
    return f"{index + 1}: {props.get('plot_no') or '(plot_no မရှိ)'} / {props.get('yard_no') or '(yard_no မရှိ)'}"

selected_delete = st.selectbox(
    "ဖျက်လိုသော polygon",
    options=list(range(len(features))),
    format_func=feature_label,
    key="delete_feature_select",
)
if st.button("ရွေးထားသော polygon ဖျက်ရန်"):
    st.session_state.features.pop(selected_delete)
    save_features(st.session_state.features)
    st.session_state.map_revision += 1
    st.rerun()

st.subheader("ဖိုင်အဖြစ် Download လုပ်ပါ")
gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
for column in ("plot_no", "yard_no"):
    if column not in gdf.columns:
        gdf[column] = ""
    gdf[column] = gdf[column].fillna("").astype(str)
geojson_bytes = gdf.to_json(drop_id=True, ensure_ascii=False).encode("utf-8")

with tempfile.TemporaryDirectory() as temp_dir:
    temp_path = Path(temp_dir)
    gpkg_path = temp_path / "plots.gpkg"
    gdf.to_file(gpkg_path, layer="plots", driver="GPKG", engine="pyogrio", index=False)
    gpkg_bytes = gpkg_path.read_bytes()

    shp_path = temp_path / "plots.shp"
    gdf.to_file(
        shp_path,
        driver="ESRI Shapefile",
        engine="pyogrio",
        encoding="UTF-8",
        index=False,
    )
    shp_zip_path = temp_path / "plots_shapefile.zip"
    with zipfile.ZipFile(shp_zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for sidecar in temp_path.glob("plots.*"):
            if sidecar.is_file() and sidecar.suffix.lower() != ".gpkg":
                archive.write(sidecar, arcname=sidecar.name)
    shapefile_zip_bytes = shp_zip_path.read_bytes()

out1, out2, out3 = st.columns(3)
with out1:
    st.download_button(
        "GeoJSON Download",
        data=geojson_bytes,
        file_name="plots.geojson",
        mime="application/geo+json",
        use_container_width=True,
    )
with out2:
    st.download_button(
        "GeoPackage Download",
        data=gpkg_bytes,
        file_name="plots.gpkg",
        mime="application/geopackage+sqlite3",
        use_container_width=True,
    )
with out3:
    st.download_button(
        "Shapefile ZIP Download",
        data=shapefile_zip_bytes,
        file_name="plots_shapefile.zip",
        mime="application/zip",
        use_container_width=True,
    )

st.caption(f"Local data file: {LOCAL_DATA_PATH}")
st.caption(
    "Output CRS: EPSG:4326 (WGS 84). Shapefile ကို companion ဖိုင်များပါဝင်စေရန် ZIP အဖြစ်ပေးထားသည်။ "
    "Satellite tiles ကြည့်ရန် internet လိုအပ်ပါသည်။"
)

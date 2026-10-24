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
from shapely.geometry import Point, shape
from folium.plugins import Draw
from streamlit_folium import st_folium
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Plot GeoJSON Digitizer", layout="wide")
st.markdown(
    """
    <style>
    .block-container { padding-top: 0.45rem; padding-bottom: 0.6rem; }
    h1 { font-size: 1.15rem !important; margin: 0 0 0.15rem 0 !important; }
    h2, h3 { font-size: 0.92rem !important; margin: 0.35rem 0 0.2rem 0 !important; }
    [data-testid="stCaptionContainer"] p { font-size: 0.76rem !important; margin: 0.1rem 0 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown("### Plot / Yard မြေပုံရေးဆွဲခြင်း")
st.caption("Satellite map သို့မဟုတ် Vector map ပေါ်မှာ plot ဆွဲပြီး plot/yard နံပါတ် ဖြည့်ပါ။ Browser tab အားလုံးမှာ polygon များ shared ဖြစ်ပါမည်။")

SHARED_STATE_PATH = Path(__file__).with_name("shared_polygons.json")


def load_shared_features():
    try:
        if SHARED_STATE_PATH.exists():
            data = json.loads(SHARED_STATE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_shared_features(features):
    temp_path = SHARED_STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(SHARED_STATE_PATH)


def geometry_key(feature):
    return json.dumps(feature["geometry"], sort_keys=True, separators=(",", ":"))


def merge_features(*feature_lists):
    merged = []
    seen = set()
    for feature_list in feature_lists:
        for feature in feature_list:
            try:
                key = geometry_key(feature)
            except (KeyError, TypeError):
                continue
            if key not in seen:
                merged.append(feature)
                seen.add(key)
    return merged


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
    return {"type": "Feature", "properties": feature.get("properties") or {}, "geometry": geometry}


def feature_index_at_point(features, lat, lng):
    """Return the topmost saved polygon that contains a clicked map coordinate."""
    point = Point(float(lng), float(lat))
    for index in range(len(features) - 1, -1, -1):
        try:
            if shape(features[index]["geometry"]).covers(point):
                return index
        except (KeyError, TypeError, ValueError):
            continue
    return None


def read_uploaded_vector(uploaded_file):
    """GeoJSON/GPKG/Shapefile ZIP ကို EPSG:4326 GeoJSON dict ပြောင်းသည်။"""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / uploaded_file.name
        source_path.write_bytes(uploaded_file.getvalue())
        read_path = source_path
        if suffix == ".zip":
            with zipfile.ZipFile(source_path) as archive:
                archive.extractall(temp_path / "unzipped")
            shapefiles = list((temp_path / "unzipped").rglob("*.shp"))
            if not shapefiles:
                raise ValueError("ZIP ထဲတွင် .shp ဖိုင်မတွေ့ပါ။")
            read_path = shapefiles[0]
        gdf = gpd.read_file(read_path)
        if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        elif gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        return json.loads(gdf.to_json(drop_id=True, ensure_ascii=False))


def image_data_uri(uploaded_file):
    mime = uploaded_file.type or "image/jpeg"
    encoded = base64.b64encode(uploaded_file.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


if "features" not in st.session_state:
    st.session_state.features = load_shared_features()

# Every tab checks the shared file periodically so polygons drawn in another tab appear.
st_autorefresh(interval=3000, key="shared_polygon_refresh")
st.session_state.features = merge_features(st.session_state.features, load_shared_features())

with st.sidebar:
    st.header("မြေပုံတည်နေရာ")
    center_lat = st.number_input("Center latitude", value=0.0, format="%.6f")
    center_lon = st.number_input("Center longitude", value=0.0, format="%.6f")
    zoom_level = st.slider("Zoom", min_value=2, max_value=23, value=2)
    offline_mode = st.checkbox("Offline mode", value=False, key="offline_mode_v2", help="ဖွင့်ထားလျှင် online Esri/OSM tile မခေါ်ဘဲ local upload layer များကိုသာသုံးသည်။")
    st.caption("Offline အတွက် local layer ထည့်ရန်")
    satellite_upload = st.file_uploader("Satellite image (PNG/JPG)", type=["png", "jpg", "jpeg"], key="offline_satellite_upload")
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
            st.session_state.local_satellite["bounds"] = [[image_south, image_west], [image_north, image_east]]
    if vector_upload is not None:
        vector_hash = hashlib.md5(vector_upload.getvalue()).hexdigest()
        if st.session_state.get("vector_hash") != vector_hash:
            try:
                st.session_state.local_vector = read_uploaded_vector(vector_upload)
                st.session_state.vector_hash = vector_hash
                st.success("Local vector layer ထည့်ပြီးပါပြီ။")
            except Exception as exc:
                st.error(f"Vector ဖိုင်ဖတ်မရပါ: {exc}")
    if st.button("Shared polygons ပြန်ဖတ်ရန်"):
        st.session_state.features = load_shared_features()
        st.rerun()
    if st.button("Polygon အားလုံး ဖျက်ရန်"):
        st.session_state.features = []
        save_shared_features([])
        st.rerun()

# Keep the current map view across Streamlit reruns (including after a drawing is saved).
sidebar_view = (float(center_lat), float(center_lon), int(zoom_level))
previous_sidebar_view = st.session_state.get("_map_sidebar_view")
if "map_view_center" not in st.session_state or previous_sidebar_view != sidebar_view:
    st.session_state.map_view_center = sidebar_view[:2]
    st.session_state.map_view_zoom = sidebar_view[2]
st.session_state["_map_sidebar_view"] = sidebar_view

map_obj = folium.Map(
    location=list(st.session_state.map_view_center),
    zoom_start=st.session_state.map_view_zoom,
    tiles=None,
    control_scale=True,
)
local_satellite = st.session_state.get("local_satellite")
local_vector = st.session_state.get("local_vector")
if offline_mode and not local_satellite and not local_vector:
    st.warning("Offline mode ဖွင့်ထားသော်လည်း local satellite/vector layer မရှိသေးပါ။ နောက်ခံမြေပုံပေါ်ရန် Offline mode ကို ပိတ်ပါ သို့မဟုတ် local layer upload လုပ်ပါ။")
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
            "color": "#1769aa",
            "weight": 2,
            "fillColor": "#4dabf7",
            "fillOpacity": 0.18,
        },
        show=True,
    ).add_to(map_obj)

for number, feature in enumerate(st.session_state.features, start=1):
    props = feature.get("properties") or {}
    label = f"Plot: {props.get('plot_no', '')} | Yard: {props.get('yard_no', '')}"
    folium.GeoJson(
        feature,
        name=f"Plot {number}",
        tooltip=label,
        style_function=lambda _feature: {
            "color": "#ff3333",
            "weight": 3,
            "fillColor": "#ff5555",
            "fillOpacity": 0.25,
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
    edit_options={"edit": True, "remove": True},
    export=False,
).add_to(map_obj)
folium.LayerControl().add_to(map_obj)

map_col, list_col = st.columns([4, 1.35], gap="small")
with map_col:
    st.caption("Map toolbar မှ polygon/rectangle ဆွဲပါ။ ဆွဲပြီးသားအကွက်ကို တိုက်ရိုက်နှိပ်၍ Plot/Yard number ဖြည့်နိုင်ပါသည်။")
    map_result = st_folium(
        map_obj,
        height=560,
        use_container_width=True,
        returned_objects=["all_drawings", "center", "zoom", "last_object_clicked", "last_object_clicked_count"],
        key="plot_map",
    )

if map_result:
    current_center = map_result.get("center")
    if isinstance(current_center, dict) and current_center.get("lat") is not None and current_center.get("lng") is not None:
        st.session_state.map_view_center = (
            float(current_center["lat"]),
            float(current_center["lng"]),
        )
    current_zoom = map_result.get("zoom")
    if current_zoom is not None:
        st.session_state.map_view_zoom = max(2, min(23, int(round(float(current_zoom)))))
    click_count = map_result.get("last_object_clicked_count")
    if click_count is not None:
        previous_click_count = st.session_state.get("_last_map_click_count", -1)
        if click_count != previous_click_count:
            st.session_state["_last_map_click_count"] = click_count
            clicked = map_result.get("last_object_clicked") or {}
            clicked_index = None
            if isinstance(clicked, dict) and clicked.get("lat") is not None and clicked.get("lng") is not None:
                clicked_index = feature_index_at_point(
                    st.session_state.features,
                    clicked["lat"],
                    clicked["lng"],
                )
            st.session_state["_pending_map_edit"] = None
            if clicked_index is not None:
                clicked_props = st.session_state.features[clicked_index].get("properties") or {}
                st.session_state["_pending_map_edit"] = {
                    "index": clicked_index,
                    "feature_id": str(clicked_props.get("feature_id", "")),
                }

def show_feature_edit_dialog(feature_index, feature_id):
    dialog_key = feature_id or f"legacy-{feature_index}"
    current_index = feature_index
    if feature_id:
        current_index = next(
            (
                index
                for index, feature in enumerate(st.session_state.features)
                if str((feature.get("properties") or {}).get("feature_id", "")) == feature_id
            ),
            -1,
        )
    if current_index < 0 or current_index >= len(st.session_state.features):
        st.warning("ဤအကွက်ကို မတွေ့တော့ပါ။")
        return
    current_props = st.session_state.features[current_index].setdefault("properties", {})
    plot_input_key = f"edit_plot_no_{dialog_key}"
    yard_input_key = f"edit_yard_no_{dialog_key}"
    st.session_state[plot_input_key] = str(current_props.get("plot_no", ""))
    st.session_state[yard_input_key] = str(current_props.get("yard_no", ""))

    @st.dialog("အကွက်အချက်အလက် ပြင်ရန်")
    def edit_dialog():
        current_index = feature_index
        if feature_id:
            current_index = next(
                (
                    index
                    for index, feature in enumerate(st.session_state.features)
                    if str((feature.get("properties") or {}).get("feature_id", "")) == feature_id
                ),
                -1,
            )
        if current_index < 0 or current_index >= len(st.session_state.features):
            st.warning("ဤအကွက်ကို မတွေ့တော့ပါ။")
            return

        props = st.session_state.features[current_index].setdefault("properties", {})
        with st.form(key=f"edit_feature_form_{dialog_key}"):
            plot_no = st.text_input("Plot number", key=plot_input_key)
            yard_no = st.text_input("Yard number", key=yard_input_key)
            submitted = st.form_submit_button("သိမ်းမည်", use_container_width=True)
        if submitted:
            props["plot_no"] = plot_no
            props["yard_no"] = yard_no
            save_shared_features(st.session_state.features)
            st.session_state["_attribute_table_revision"] = st.session_state.get("_attribute_table_revision", 0) + 1
            st.rerun()

    edit_dialog()

pending_map_edit = st.session_state.pop("_pending_map_edit", None)
if pending_map_edit:
    show_feature_edit_dialog(pending_map_edit["index"], pending_map_edit["feature_id"])

with list_col:
    st.markdown("#### ဆွဲပြီးသောအကွက်များ")
    if not st.session_state.features:
        st.caption("အကွက်မရှိသေးပါ။")
    else:
        st.caption(f"စုစုပေါင်း {len(st.session_state.features)} ကွက်")
        for index, saved_feature in enumerate(st.session_state.features):
            saved_props = saved_feature.get("properties") or {}
            saved_plot = saved_props.get("plot_no") or "(plot မဖြည့်ရသေး)"
            saved_yard = saved_props.get("yard_no") or "(yard မဖြည့်ရသေး)"
            with st.container(border=True):
                st.caption(f"ကွက် {index + 1}")
                st.write(f"**{saved_plot}**")
                st.caption(f"Yard: {saved_yard}")
                feature_id = str(saved_props.get("feature_id", ""))
                edit_col, delete_col = st.columns(2)
                with edit_col:
                    if st.button("ပြင်ရန်", key=f"edit_list_{feature_id or index}", use_container_width=True):
                        show_feature_edit_dialog(index, feature_id)
                with delete_col:
                    if st.button("ဖျက်ရန်", key=f"delete_list_{feature_id or index}", use_container_width=True):
                        st.session_state.features.pop(index)
                        save_shared_features(st.session_state.features)
                        st.rerun()

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
    feature["properties"].update({"feature_id": str(uuid.uuid4()), "plot_no": "", "yard_no": ""})
    st.session_state.features.append(feature)
    known_geometries.add(key)
    new_feature_added = True
if new_feature_added:
    save_shared_features(st.session_state.features)
    st.rerun()

features = st.session_state.features
if not features:
    st.info("Polygon မရှိသေးပါ။ Map toolbar မှ polygon တစ်ခု အရင်ဆွဲပါ။")
    st.stop()

st.markdown("#### ၂။ Plot ဖြည့်ကွက်နှင့် ၃။ Polygon ဖျက်ခြင်း")
edit_col, delete_col = st.columns([4, 1.35], gap="small")
with edit_col:
    st.caption("Plot number နှင့် Yard number ကို ဇယားထဲတွင် ဖြည့်ပါ။")
rows = []
for index, feature in enumerate(features):
    props = feature.setdefault("properties", {})
    rows.append({"Feature": index + 1, "plot_no": str(props.get("plot_no", "")), "yard_no": str(props.get("yard_no", ""))})
attribute_df = pd.DataFrame(rows)
feature_ids = [str(feature["properties"].get("feature_id", index)) for index, feature in enumerate(features)]
with edit_col:
    edited_df = st.data_editor(
        attribute_df,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=["Feature"],
        key="plot_attributes_" + "_".join(feature_ids) + f"_v{st.session_state.get('_attribute_table_revision', 0)}",
        column_config={
            "Feature": st.column_config.NumberColumn("Feature", format="%d"),
            "plot_no": st.column_config.TextColumn("Plot number", help="ဥပမာ P-001"),
            "yard_no": st.column_config.TextColumn("Yard number", help="ဥပမာ Y-05"),
        },
    )
attributes_changed = False
for index, row in edited_df.iterrows():
    props = features[index].setdefault("properties", {})
    new_plot_no = str(row["plot_no"])
    new_yard_no = str(row["yard_no"])
    if props.get("plot_no", "") != new_plot_no:
        props["plot_no"] = new_plot_no
        attributes_changed = True
    if props.get("yard_no", "") != new_yard_no:
        props["yard_no"] = new_yard_no
        attributes_changed = True
if attributes_changed:
    save_shared_features(features)
    st.rerun()

def feature_label(index):
    props = features[index].get("properties", {})
    return f"{index + 1}: {props.get('plot_no') or '(plot_no မရှိ)'} / {props.get('yard_no') or '(yard_no မရှိ)'}"
with delete_col:
    st.caption("မကြိုက်သော polygon ကို ရွေးပြီး ဖျက်ပါ။")
    selected_index = st.selectbox("ဖျက်လိုသော polygon", options=list(range(len(features))), format_func=feature_label)
    if st.button("ရွေးထားတာ ဖျက်ရန်", use_container_width=True):
        st.session_state.features.pop(selected_index)
        save_shared_features(st.session_state.features)
        st.rerun()

st.subheader("၄။ ဖိုင်အဖြစ် Download လုပ်ပါ")
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
    gdf.to_file(shp_path, driver="ESRI Shapefile", engine="pyogrio", encoding="UTF-8", index=False)
    shp_zip_path = temp_path / "plots_shapefile.zip"
    with zipfile.ZipFile(shp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as shp_zip:
        for sidecar in temp_path.glob("plots.*"):
            if sidecar.is_file() and sidecar.suffix.lower() != ".gpkg":
                shp_zip.write(sidecar, arcname=sidecar.name)
    shapefile_zip_bytes = shp_zip_path.read_bytes()

download_col1, download_col2, download_col3 = st.columns(3)
with download_col1:
    st.download_button("GeoJSON Download", data=geojson_bytes, file_name="plots.geojson", mime="application/geo+json", use_container_width=True)
with download_col2:
    st.download_button("GeoPackage Download", data=gpkg_bytes, file_name="plots.gpkg", mime="application/geopackage+sqlite3", use_container_width=True)
with download_col3:
    st.download_button("Shapefile ZIP Download", data=shapefile_zip_bytes, file_name="plots_shapefile.zip", mime="application/zip", use_container_width=True)
st.caption("Output CRS: EPSG:4326 (WGS 84). Shapefile တွင် companion ဖိုင်များလိုအပ်သောကြောင့် ZIP အဖြစ်ပေးထားသည်။")

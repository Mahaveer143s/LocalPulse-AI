import os
import time
from html import escape
from io import BytesIO

import requests
import streamlit as st
from openpyxl import Workbook

try:
    import google.generativeai as genai
except ImportError:
    genai = None


GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_USER_AGENT = "LocalPulse-AI/1.0 (support@localpulse.ai)"
SUPPORT_EMAIL = "support@localpulse.ai"
SUPPORT_PHONE = "+91 90000 00000"


st.set_page_config(
    page_title="Smart Lead Generator",
    page_icon="SL",
    layout="wide",
)


def get_secret(name: str, default: str = "") -> str:
    if name in st.secrets:
        return st.secrets[name]
    return os.getenv(name, default)


def init_session() -> None:
    defaults = {
        "is_logged_in": False,
        "user_name": "",
        "user_email": "",
        "user_role": "Business User",
        "user_google_api_key": "",
        "user_gemini_api_key": "",
    }

    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def has_user_api_keys() -> bool:
    return bool(st.session_state.user_google_api_key and st.session_state.user_gemini_api_key)


def render_login() -> None:
    st.title("LocalPulse-AI")
    st.caption("Sign in to generate local business leads.")

    with st.form("login_form"):
        name = st.text_input("Name")
        email = st.text_input("Email")
        role = st.radio("Account type", ["Business User", "Developer"], horizontal=True)
        submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

    if submitted:
        if not name.strip() or not email.strip():
            st.error("Please enter your name and email.")
            st.stop()

        st.session_state.is_logged_in = True
        st.session_state.user_name = name.strip()
        st.session_state.user_email = email.strip()
        st.session_state.user_role = role
        st.rerun()


def render_profile() -> None:
    st.title("Profile")
    st.caption(f"Logged in as {st.session_state.user_name} ({st.session_state.user_role})")

    if st.session_state.user_role == "Developer":
        st.subheader("Developer API Keys")
        st.info("These keys are kept only in your current browser session. They are not saved to GitHub.")

        with st.form("api_keys_form"):
            google_key = st.text_input(
                "Google Maps API Key",
                value=st.session_state.user_google_api_key,
                type="password",
            )
            gemini_key = st.text_input(
                "Gemini API Key",
                value=st.session_state.user_gemini_api_key,
                type="password",
            )
            saved = st.form_submit_button("Save Keys", type="primary", use_container_width=True)

        if saved:
            st.session_state.user_google_api_key = google_key.strip()
            st.session_state.user_gemini_api_key = gemini_key.strip()
            st.success("API keys saved for this session.")

        if has_user_api_keys():
            st.success("Developer keys are ready. Go to Generate Leads.")
        else:
            st.warning("Add both keys to run real Google Places + Gemini searches.")
    else:
        render_support()


def render_support() -> None:
    st.subheader("Contact Support")
    st.write("If you are not a developer, contact us and we will help you set up lead generation.")
    st.write(f"Email: {SUPPORT_EMAIL}")
    st.write(f"Phone: {SUPPORT_PHONE}")
    st.link_button("Send Email", f"mailto:{SUPPORT_EMAIL}?subject=LocalPulse-AI%20Support")


def get_high_demand_areas(city: str, state: str, business_type: str, gemini_api_key: str) -> list[str]:
    if genai is None:
        raise RuntimeError("google-generativeai is not installed. Run: pip install -r requirements.txt")

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = f"""
Suggest top 5 high demand areas in {city}, {state}, India where {business_type}
services are highly needed.

Only return area names in comma-separated format. Do not include numbering.
"""
    response = model.generate_content(prompt)
    text = getattr(response, "text", "") or ""
    areas = [area.strip(" \n\t.-0123456789") for area in text.split(",")]
    return [area for area in areas if area][:5]


def search_places(query: str, location: str, google_api_key: str) -> list[dict]:
    params = {
        "query": f"{query} in {location}",
        "key": google_api_key,
    }
    results = []

    for _ in range(3):
        response = requests.get(GOOGLE_PLACES_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status")
        if status not in {"OK", "ZERO_RESULTS"}:
            message = payload.get("error_message", status or "Unknown Google Places error")
            raise RuntimeError(message)

        results.extend(payload.get("results", []))

        next_page_token = payload.get("next_page_token")
        if not next_page_token:
            break

        time.sleep(2)
        params = {
            "pagetoken": next_page_token,
            "key": google_api_key,
        }

    return results


def get_details(place_id: str, google_api_key: str) -> dict:
    params = {
        "place_id": place_id,
        "fields": "name,formatted_phone_number,formatted_address,website,rating",
        "key": google_api_key,
    }
    response = requests.get(GOOGLE_DETAILS_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()

    status = payload.get("status")
    if status not in {"OK", "ZERO_RESULTS"}:
        message = payload.get("error_message", status or "Unknown Google Place Details error")
        raise RuntimeError(message)

    return payload.get("result", {})


def get_osm_bbox(location: str) -> list[float]:
    params = {
        "q": location,
        "format": "json",
        "limit": 1,
    }
    response = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": OSM_USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if not payload:
        raise RuntimeError(f"OpenStreetMap could not find {location}")

    south, north, west, east = payload[0]["boundingbox"]
    return [float(south), float(west), float(north), float(east)]


def get_osm_filters(business_type: str) -> list[tuple[str, str]]:
    filters = {
        "Interior Designers": [("office", "interior_design"), ("shop", "furniture")],
        "Builders": [("office", "construction_company"), ("craft", "builder")],
        "Construction": [("office", "construction_company"), ("craft", "builder")],
        "Web Development": [("office", "it"), ("office", "company")],
        "Real Estate": [("office", "estate_agent")],
    }
    return filters.get(business_type, [("office", "company")])


def build_osm_query(business_type: str, bbox: str, limit: int, broad: bool = False) -> str:
    if broad:
        selectors = [
            f'node["office"]["name"]({bbox});',
            f'way["office"]["name"]({bbox});',
            f'relation["office"]["name"]({bbox});',
            f'node["shop"]["name"]({bbox});',
            f'way["shop"]["name"]({bbox});',
            f'relation["shop"]["name"]({bbox});',
        ]
    else:
        selectors = []
        for key, value in get_osm_filters(business_type):
            selectors.extend(
                [
                    f'node["{key}"="{value}"]({bbox});',
                    f'way["{key}"="{value}"]({bbox});',
                    f'relation["{key}"="{value}"]({bbox});',
                ]
            )

    return f"""
[out:json][timeout:25];
(
  {''.join(selectors)}
);
out center tags {limit};
"""


def rows_from_osm_elements(elements: list[dict], location: str, limit: int) -> list[dict]:
    rows = []

    for element in elements:
        if len(rows) >= limit:
            break

        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        address_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:suburb"),
            tags.get("addr:city"),
        ]
        address = ", ".join(part for part in address_parts if part) or location

        rows.append(
            {
                "Name": name,
                "Phone": tags.get("phone") or tags.get("contact:phone"),
                "Address": address,
                "Website": tags.get("website") or tags.get("contact:website"),
                "Rating": "",
                "Area": location.split(",")[0].strip(),
            }
        )

    return rows


def run_overpass_query(query: str) -> list[dict]:
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": OSM_USER_AGENT},
        timeout=35,
    )
    response.raise_for_status()
    return response.json().get("elements", [])


def search_osm_places(business_type: str, location: str, limit: int) -> list[dict]:
    south, west, north, east = get_osm_bbox(location)
    bbox = f"{south},{west},{north},{east}"
    rows = rows_from_osm_elements(run_overpass_query(build_osm_query(business_type, bbox, limit)), location, limit)

    if rows:
        return rows

    city_location = ", ".join(part.strip() for part in location.split(",")[1:] if part.strip())
    fallback_location = city_location or location
    south, west, north, east = get_osm_bbox(fallback_location)
    bbox = f"{south},{west},{north},{east}"
    elements = run_overpass_query(build_osm_query(business_type, bbox, limit * 3, broad=True))
    return rows_from_osm_elements(elements, location, limit)


LEAD_COLUMNS = ["Name", "Phone", "Address", "Website", "Rating", "Area"]


def build_excel_download(rows: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Leads"
    sheet.append(LEAD_COLUMNS)

    for row in rows:
        sheet.append([row.get(column, "") for column in LEAD_COLUMNS])

    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 55)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def render_leads_table(rows: list[dict]) -> None:
    if not rows:
        st.warning("No leads found.")
        return

    header = "".join(f"<th>{escape(column)}</th>" for column in LEAD_COLUMNS)
    body = []

    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(column) or ''))}</td>" for column in LEAD_COLUMNS)
        body.append(f"<tr>{cells}</tr>")

    st.markdown(
        f"""
<div class="leads-table-wrap">
  <table class="leads-table">
    <thead><tr>{header}</tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</div>
""",
        unsafe_allow_html=True,
    )


def demo_areas(city: str) -> list[str]:
    sample = {
        "hyderabad": ["Gachibowli", "Madhapur", "Kondapur", "Jubilee Hills", "Banjara Hills"],
        "vijayawada": ["Benz Circle", "Governorpet", "Patamata", "Auto Nagar", "Moghalrajpuram"],
        "bengaluru": ["Indiranagar", "Whitefield", "Koramangala", "HSR Layout", "Jayanagar"],
        "bangalore": ["Indiranagar", "Whitefield", "Koramangala", "HSR Layout", "Jayanagar"],
    }
    return sample.get(city.lower().strip(), ["Central Area", "Business District", "Main Road", "Tech Park", "Market Area"])


def demo_leads(city: str, state: str, business_type: str, areas: list[str]) -> list[dict]:
    rows = []
    for area in areas:
        for index in range(1, 4):
            rows.append(
                {
                    "Name": f"{area} {business_type} Lead {index}",
                    "Phone": f"+91 90000 00{index:03d}",
                    "Address": f"{area}, {city}, {state}, India",
                    "Website": f"https://example.com/{area.lower().replace(' ', '-')}-{index}",
                    "Rating": round(4.0 + index / 10, 1),
                    "Area": area,
                }
            )
    return rows


def render_api_keys_help() -> None:
    with st.sidebar.expander("API key setup"):
        st.write("Developers can add keys from Profile. Deployed app owners can also add Streamlit secrets:")
        st.code(
            """GOOGLE_API_KEY = "your_google_places_key"
GEMINI_API_KEY = "your_gemini_key"
""",
            language="toml",
        )


st.markdown(
    """
<style>
.leads-table-wrap {
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 8px;
    overflow: auto;
    max-height: 520px;
}
.leads-table {
    border-collapse: collapse;
    min-width: 980px;
    width: 100%;
    font-size: 14px;
}
.leads-table th,
.leads-table td {
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    padding: 10px 12px;
    text-align: left;
    vertical-align: top;
}
.leads-table th {
    background: rgba(255, 255, 255, 0.08);
    font-weight: 700;
    position: sticky;
    top: 0;
}
</style>
""",
    unsafe_allow_html=True,
)

init_session()

if not st.session_state.is_logged_in:
    render_login()
    st.stop()

with st.sidebar:
    st.header("LocalPulse-AI")
    st.write(st.session_state.user_name)
    page = st.radio("Menu", ["Generate Leads", "Profile"], label_visibility="collapsed")
    if st.button("Logout", use_container_width=True):
        st.session_state.is_logged_in = False
        st.session_state.user_name = ""
        st.session_state.user_email = ""
        st.session_state.user_google_api_key = ""
        st.session_state.user_gemini_api_key = ""
        st.rerun()

if page == "Profile":
    render_profile()
    st.stop()

st.title("Smart Lead Generator")
st.caption("Find high-demand local areas with Gemini, search businesses with Google Places, and download leads as Excel.")

if st.session_state.user_role != "Developer":
    st.info("Business users can contact support for setup. Demo mode is available for testing.")

with st.sidebar:
    st.header("Settings")
    lead_source = st.selectbox("Lead source", ["OpenStreetMap Free", "Google Places"])
    use_demo_data = st.toggle("Demo mode", value=True, help="Test the UI and Excel download without API keys.")
    max_limit = 10 if lead_source == "OpenStreetMap Free" else 20
    max_places_per_area = st.slider("Max leads per area", min_value=1, max_value=max_limit, value=min(10, max_limit))
    render_api_keys_help()

google_api_key = st.session_state.user_google_api_key or get_secret("GOOGLE_API_KEY")
gemini_api_key = st.session_state.user_gemini_api_key or get_secret("GEMINI_API_KEY")

left, right = st.columns(2)

with left:
    state = st.selectbox("Select State", ["Telangana", "Andhra Pradesh", "Karnataka"])
    business_type = st.selectbox(
        "Select Business Type",
        ["Interior Designers", "Builders", "Construction", "Web Development", "Real Estate"],
    )

with right:
    city = st.text_input("Enter City", placeholder="Hyderabad, Vijayawada, Bengaluru")
    manual_areas = st.text_input("Optional: enter areas manually", placeholder="Madhapur, Kondapur, Gachibowli")

generate = st.button("Generate Leads", type="primary", use_container_width=True)

if generate:
    if not city.strip():
        st.error("Please enter a city.")
        st.stop()

    has_manual_areas = bool(manual_areas.strip())

    if st.session_state.user_role != "Developer" and not use_demo_data:
        st.error("Real lead generation is available for developers. Please contact support for setup.")
        render_support()
        st.stop()

    if not use_demo_data and lead_source == "Google Places" and not google_api_key:
        st.error("Real mode needs GOOGLE_API_KEY. Add it in Profile or turn on Demo mode.")
        st.stop()

    if not use_demo_data and not has_manual_areas and not gemini_api_key:
        st.error("AI area suggestions need GEMINI_API_KEY. Add it in Profile, enter areas manually, or turn on Demo mode.")
        st.stop()

    try:
        if has_manual_areas:
            areas = [area.strip() for area in manual_areas.split(",") if area.strip()]
        elif use_demo_data:
            with st.spinner("Preparing demo high-demand areas..."):
                areas = demo_areas(city)
        else:
            with st.spinner("Finding high-demand areas using Gemini..."):
                areas = get_high_demand_areas(city, state, business_type, gemini_api_key)

        if not areas:
            st.warning("No areas found. Try entering areas manually.")
            st.stop()

        st.success("Top areas found")
        st.write(", ".join(areas))

        if use_demo_data:
            leads = demo_leads(city, state, business_type, areas)
        else:
            all_data = []
            progress = st.progress(0)
            status = st.empty()

            for area_index, area in enumerate(areas, start=1):
                location = f"{area}, {city}, {state}, India"
                status.write(f"Searching {business_type} in {area}...")

                if lead_source == "OpenStreetMap Free":
                    all_data.extend(search_osm_places(business_type, location, max_places_per_area))
                    time.sleep(1)
                else:
                    places = search_places(business_type, location, google_api_key)

                    for place in places[:max_places_per_area]:
                        details = get_details(place["place_id"], google_api_key)
                        all_data.append(
                            {
                                "Name": details.get("name"),
                                "Phone": details.get("formatted_phone_number"),
                                "Address": details.get("formatted_address"),
                                "Website": details.get("website"),
                                "Rating": details.get("rating"),
                                "Area": area,
                            }
                        )

                progress.progress(area_index / len(areas))

            leads = all_data

            if lead_source == "OpenStreetMap Free":
                st.caption("Data source: OpenStreetMap contributors. Free source may have fewer phone numbers and websites.")

        st.subheader("Generated Leads")
        st.caption(f"{len(leads)} leads")
        render_leads_table(leads)

        excel_data = build_excel_download(leads)
        st.download_button(
            "Download Excel",
            data=excel_data,
            file_name=f"{city.strip().lower().replace(' ', '_')}_leads.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as exc:
        st.error(f"Something went wrong: {exc}")

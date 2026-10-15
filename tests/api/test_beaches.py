"""The deployment-site model: one active beach, cameras scoped to it, one search box to set it up."""
from __future__ import annotations

from tests.conftest import ADMIN, LIFEGUARD, OPERATOR


def test_installation_is_seeded_with_the_configured_beach(beach):
    """A fresh install is never empty: the beach from .env becomes the deployment site."""
    assert beach["is_active"] is True
    assert beach["name"] == "Tannirbhavi Beach, Mangaluru" and beach["region"] == "Karnataka, India"


def test_public_config_reports_the_active_beach_and_its_position(client, beach):
    cfg = client.get("/api/config/public", headers=LIFEGUARD).json()
    assert cfg["beach"]["id"] == beach["id"]
    # The location must be visible to the interfaces, not implied.
    assert cfg["beach"]["lat"] == beach["lat"] and cfg["beach"]["lon"] == beach["lon"]
    assert cfg["lat"] == beach["lat"]


def test_public_config_says_whether_search_and_tiles_are_available(client):
    caps = client.get("/api/config/public", headers=LIFEGUARD).json()["capabilities"]
    # The test settings use the mock provider and no key, so both are off - and say so.
    assert caps["place_search"] is False and caps["map_tiles"] is False


def test_map_tiles_are_served_from_this_app_not_the_provider(client):
    """The API key must never appear in a URL the browser fetches."""
    m = client.get("/api/config/public", headers=LIFEGUARD).json()["map"]
    assert m["tile_url"].startswith("/api/map/tiles/")
    assert "apiKey" not in m["tile_url"] and "geoapify.com" not in m["tile_url"]
    assert "{z}" in m["tile_url"] and "{x}" in m["tile_url"] and "{y}" in m["tile_url"]


def test_a_tile_request_without_a_key_returns_a_blank_png_not_an_error(client):
    """A map with gaps is usable; a map that throws is not."""
    r = client.get("/api/map/tiles/osm-bright-smooth/12/2930/1800.png", headers=OPERATOR)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_tiles_are_served_to_an_unauthenticated_request(client):
    """Regression: Leaflet fetches tiles as <img>, which cannot send X-Dev-Role or a bearer token.

    A role guard on this route answers 401 to its only caller and the Control Room map renders
    blank. The key stays server-side either way, so the route is deliberately open; see the module
    docstring in app/environment/api/tiles.py.
    """
    r = client.get("/api/map/tiles/osm-bright-smooth/12/2930/1800.png")  # no auth headers at all
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_a_beach_cannot_be_created_at_null_island(client):
    """0,0 is an empty coordinate field, not a site. Accepting it yields a beach whose map, weather
    and camera placement all describe the wrong hemisphere."""
    r = client.post("/api/beaches", headers=ADMIN,
                    json={"name": "Nowhere Beach", "lat": 0, "lon": 0})
    assert r.status_code == 422


def test_a_beach_on_a_real_coastline_is_still_accepted(client):
    """The null-island guard must not reject a legitimate site that merely has a zero in it."""
    r = client.post("/api/beaches", headers=ADMIN,
                    json={"name": "Panambur Beach", "region": "Mangaluru, Karnataka",
                          "lat": 12.9259, "lon": 74.8044, "activate": False})
    assert r.status_code in (200, 201), r.text


def test_a_silly_tile_style_is_rejected(client):
    assert client.get("/api/map/tiles/..%2Fsecret/12/1/1.png", headers=OPERATOR).status_code in (404, 422)


def test_new_cameras_attach_to_the_active_beach(client, beach, camera):
    assert camera["beach_id"] == beach["id"]
    listed = client.get(f"/api/cameras?beach_id={beach['id']}", headers=OPERATOR).json()
    assert [c["id"] for c in listed] == [camera["id"]]
    assert client.get("/api/cameras?beach_id=bch_elsewhere", headers=OPERATOR).json() == []


def test_active_beach_reports_its_camera_count(client, beach, camera):
    sites = client.get("/api/beaches", headers=OPERATOR).json()
    assert len(sites) == 1 and sites[0]["camera_count"] == 1


def test_picking_a_beach_during_setup_makes_it_the_deployment(client, beach):
    """Choosing a place in the picker means 'watch this one' - that is the only reason to pick it."""
    picked = client.post("/api/beaches", headers=OPERATOR, json={
        "name": "Panambur Beach", "lat": 12.93, "lon": 74.80,
        "region": "Mangaluru, Karnataka, India", "source_id": "geo-p2"}).json()
    assert picked["is_active"] is True
    assert client.get("/api/beaches/active", headers=OPERATOR).json()["id"] == picked["id"]


def test_a_site_can_be_added_without_taking_over(client, beach):
    second = client.post("/api/beaches", headers=OPERATOR, json={
        "name": "Someshwara Beach", "lat": 12.78, "lon": 74.86, "activate": False}).json()
    assert second["is_active"] is False
    assert client.get("/api/beaches/active", headers=OPERATOR).json()["id"] == beach["id"]


def test_activating_a_beach_deactivates_every_other(client, beach):
    second = client.post("/api/beaches", headers=OPERATOR, json={
        "name": "Panambur Beach", "lat": 12.93, "lon": 74.80, "activate": False}).json()
    activated = client.post(f"/api/beaches/{second['id']}/activate", headers=ADMIN).json()
    assert activated["is_active"] is True
    sites = client.get("/api/beaches", headers=OPERATOR).json()
    assert [s["is_active"] for s in sites].count(True) == 1
    assert sites[0]["id"] == second["id"]  # the active site is listed first


def test_changing_the_deployment_is_a_controller_action_not_a_lifeguard_one(client, beach):
    """One beach, one authority: the controller who watches the site also configures it. The
    lifeguard app stays read-and-acknowledge, which is the separation that actually matters."""
    assert client.post(f"/api/beaches/{beach['id']}/activate", headers=OPERATOR).status_code == 200
    assert client.post(f"/api/beaches/{beach['id']}/activate", headers=LIFEGUARD).status_code == 403


def test_adding_the_same_map_result_twice_updates_instead_of_duplicating(client):
    body = {"name": "Someshwara Beach", "lat": 12.78, "lon": 74.86, "source_id": "geo-abc"}
    first = client.post("/api/beaches", headers=OPERATOR, json=body).json()
    again = client.post("/api/beaches", headers=OPERATOR, json={**body, "lifeguard_count": 3}).json()
    assert again["id"] == first["id"] and again["lifeguard_count"] == 3
    assert len(client.get("/api/beaches", headers=OPERATOR).json()) == 2  # seeded + this one


def test_a_beach_can_be_typed_in_by_hand_with_no_region(client):
    """What the operator does when the lookup is unavailable."""
    made = client.post("/api/beaches", headers=OPERATOR,
                       json={"name": "Unlisted cove", "lat": 10.0, "lon": 76.0})
    assert made.status_code == 201 and made.json()["region"] == ""


def test_authority_details_are_editable_but_position_is_not(client, beach):
    updated = client.patch(f"/api/beaches/{beach['id']}", headers=OPERATOR, json={
        "authority_name": "Mangaluru Coastal Authority", "authority_phone": "+91 824 000000",
        "lifeguard_count": 4}).json()
    assert updated["authority_name"] == "Mangaluru Coastal Authority" and updated["lifeguard_count"] == 4
    assert client.patch(f"/api/beaches/{beach['id']}", headers=OPERATOR,
                        json={"lat": 1.0}).status_code == 422
    assert client.patch(f"/api/beaches/{beach['id']}", headers=OPERATOR,
                        json={"lifeguard_count": -1}).status_code == 422


def test_place_search_reports_why_it_is_empty_instead_of_just_returning_nothing(client):
    """With the mock provider the operator is told to type the place in, not left guessing."""
    body = client.get("/api/places/search?q=panambur", headers=OPERATOR).json()
    assert body["results"] == [] and body["available"] is False
    assert body["error"] and body["query"] == "panambur"


def test_nearby_beaches_uses_the_same_shape(client, beach):
    body = client.get(f"/api/places/beaches-near?lat={beach['lat']}&lon={beach['lon']}",
                      headers=OPERATOR).json()
    assert body["results"] == [] and body["available"] is False and body["error"]


def test_a_too_short_query_is_rejected(client):
    assert client.get("/api/places/search?q=a", headers=OPERATOR).status_code == 422
    assert client.get("/api/places/search", headers=OPERATOR).status_code == 422


def test_unknown_beach_is_a_404_not_a_dangling_camera(client):
    assert client.patch("/api/beaches/bch_missing", headers=OPERATOR, json={"notes": "x"}).status_code == 404
    r = client.post("/api/cameras", headers=ADMIN, json={
        "name": "orphan", "lat": 1, "lon": 1, "stream_url": "rtsp://h/x", "beach_id": "bch_missing"})
    assert r.status_code == 404

from homeassistant.util import slugify
from homeassistant.helpers import area_registry as ar
from .const import CONF_AREA, CONF_VACUUM, CONF_SEGMENTS

def get_room_identity(hass, room, is_duplicate):
    """
    Determine the unique slug and display name for a room.
    If is_duplicate is True, tries to fetch the room name from the vacuum entity.
    """
    area_id = room[CONF_AREA]
    area_reg = ar.async_get(hass)
    area_entry = area_reg.async_get_area(area_id)
    ha_area_name = area_entry.name if area_entry else area_id
    
    if not is_duplicate:
        return slugify(area_id), ha_area_name
        
    # Handle Duplicate
    vac_id = room[CONF_VACUUM]
    segments = room.get(CONF_SEGMENTS, [])
    
    # Try to get name from vacuum
    vac_state = hass.states.get(vac_id)
    vac_room_name = None
    
    if vac_state:
        # 1. Try 'rooms' attribute (Map data)
        if segments:
            rooms_attr = vac_state.attributes.get("rooms")
            seg_id = segments[0]
            
            if isinstance(rooms_attr, dict):
                # Dict format: {1: "Kitchen", "2": "Living"}
                if seg_id in rooms_attr:
                    vac_room_name = rooms_attr[seg_id]
                elif str(seg_id) in rooms_attr:
                    vac_room_name = rooms_attr[str(seg_id)]
            elif isinstance(rooms_attr, list):
                # List format: [{'id': 1, 'name': 'Kitchen'}, ...]
                for r in rooms_attr:
                    if isinstance(r, dict):
                        r_id = r.get('id')
                        if r_id == seg_id or str(r_id) == str(seg_id):
                            vac_room_name = r.get('name')
                            break
        
        # 2. If map name not found, use Vacuum Entity Name
        if not vac_room_name:
             vac_room_name = vac_state.attributes.get("friendly_name")

    if vac_room_name:
        # User requested: postfixed with the area name
        return slugify(f"{area_id}_{vac_room_name}"), vac_room_name
        
    # Fallback to segment ID
    suffix = "_".join(str(s) for s in segments) if segments else "unknown"
    return slugify(f"{area_id}_{suffix}"), f"{ha_area_name} {suffix}"

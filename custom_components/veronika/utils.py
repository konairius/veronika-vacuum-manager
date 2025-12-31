import logging
from homeassistant.util import slugify
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from .const import CONF_AREA, CONF_VACUUM, CONF_SEGMENTS

_LOGGER = logging.getLogger(__name__)

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
    
    vac_room_name = None
    
    if segments:
        seg_id = segments[0]
        
        # Find the entity that holds the 'rooms' attribute
        # 1. Check vacuum entity itself
        # 2. Check siblings on the same device
        
        candidates = [vac_id]
        
        ent_reg = er.async_get(hass)
        vac_entry = ent_reg.async_get(vac_id)
        
        if vac_entry and vac_entry.device_id:
            # Add all sibling entities
            siblings = er.async_entries_for_device(ent_reg, vac_entry.device_id)
            candidates.extend([e.entity_id for e in siblings if e.entity_id != vac_id])
            
        for entity_id in candidates:
            state = hass.states.get(entity_id)
            if not state:
                continue
                
            # Try multiple common attribute names
            for attr in ['rooms', 'room_list', 'regions']:
                rooms_attr = state.attributes.get(attr)
                if not rooms_attr:
                    continue
                
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
                
                if vac_room_name:
                    break
            if vac_room_name:
                break
        
    if vac_room_name:
        # User requested: postfixed with the area name
        return slugify(f"{area_id}_{vac_room_name}"), f"{ha_area_name} {vac_room_name}"
        
    # Fallback to segment ID
    suffix = "_".join(str(s) for s in segments) if segments else "unknown"
    return slugify(f"{area_id}_{suffix}"), f"{ha_area_name} {suffix}"

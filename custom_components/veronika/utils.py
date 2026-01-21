import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from .const import CONF_AREA, CONF_VACUUM, CONF_SEGMENTS

_LOGGER = logging.getLogger(__name__)

def get_area_entities(hass: HomeAssistant, area_id: str) -> List[str]:
    """Get all entity IDs in an area (direct and via devices)."""
    ent_reg: er.EntityRegistry = er.async_get(hass)
    dev_reg: dr.DeviceRegistry = dr.async_get(hass)
    
    entities: Set[str] = set()
    # Entities directly in area
    for entry in er.async_entries_for_area(ent_reg, area_id):
        entities.add(entry.entity_id)
    
    # Entities in devices in area
    for device in dr.async_entries_for_area(dev_reg, area_id):
        for entry in er.async_entries_for_device(ent_reg, device.id):
            if entry.area_id is None:
                entities.add(entry.entity_id)
    return list(entities)

def get_entity_device_class(hass: HomeAssistant, entity_id: str) -> Optional[str]:
    """Get device class for an entity, preferring state attributes over registry."""
    ent_reg: er.EntityRegistry = er.async_get(hass)
    state = hass.states.get(entity_id)
    entry: Optional[er.RegistryEntry] = ent_reg.async_get(entity_id)
    
    # Prefer state attributes (allows runtime overrides)
    if state:
        device_class = state.attributes.get("device_class")
        if device_class:
            return device_class
    
    # Fallback to registry
    if entry:
        return entry.device_class or entry.original_device_class
    
    return None

def discover_occupancy_sensors(hass: HomeAssistant, area_id: str, platform_filter: Optional[str] = None) -> List[str]:
    """Discover occupancy sensors in an area.
    
    Args:
        hass: HomeAssistant instance
        area_id: Area ID to search
        platform_filter: Platform to filter by (None to accept all)
    
    Returns:
        List of entity IDs with occupancy device class
    """
    ent_reg: er.EntityRegistry = er.async_get(hass)
    area_entities: List[str] = get_area_entities(hass, area_id)
    occupancy_sensors: List[str] = []
    
    for entity_id in area_entities:
        entry = ent_reg.async_get(entity_id)
        
        # Check platform filter
        if platform_filter and (not entry or entry.platform != platform_filter):
            continue
        
        # Check device class
        device_class = get_entity_device_class(hass, entity_id)
        if device_class == "occupancy":
            occupancy_sensors.append(entity_id)
    
    return occupancy_sensors

def discover_door_sensors(hass: HomeAssistant, area_ids: List[str]) -> List[str]:
    """Discover door sensors across multiple areas.
    
    Args:
        hass: HomeAssistant instance
        area_ids: List of area IDs to search
    
    Returns:
        List of entity IDs with door device class
    """
    door_sensors: List[str] = []
    
    for area_id in area_ids:
        area_entities = get_area_entities(hass, area_id)
        for entity_id in area_entities:
            device_class = get_entity_device_class(hass, entity_id)
            if device_class == "door":
                door_sensors.append(entity_id)
    
    return door_sensors

def get_room_identity(hass: HomeAssistant, room: Dict[str, Any], is_duplicate: bool) -> Tuple[str, str]:
    """
    Determine the unique slug and display name for a room.
    If is_duplicate is True, tries to fetch the room name from the vacuum entity.
    
    Args:
        hass: HomeAssistant instance
        room: Room configuration dictionary
        is_duplicate: Whether this is a duplicate area
    
    Returns:
        Tuple of (slug, display_name)
    """
    area_id: str = room[CONF_AREA]
    area_reg: ar.AreaRegistry = ar.async_get(hass)
    area_entry: Optional[ar.AreaEntry] = area_reg.async_get_area(area_id)
    ha_area_name: str = area_entry.name if area_entry else area_id
    
    if not is_duplicate:
        return slugify(area_id), ha_area_name
        
    # Handle Duplicate
    vac_id: str = room[CONF_VACUUM]
    segments: List[int] = room.get(CONF_SEGMENTS, [])
    
    vac_room_name: Optional[str] = None
    
    if segments:
        seg_id: int = segments[0]
        
        # Find the entity that holds the 'rooms' attribute
        # 1. Check vacuum entity itself
        # 2. Check siblings on the same device
        
        candidates: List[str] = [vac_id]
        
        ent_reg: er.EntityRegistry = er.async_get(hass)
        vac_entry: Optional[er.RegistryEntry] = ent_reg.async_get(vac_id)
        
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
                    # Dict format: {1: "Kitchen", "2": "Living"} OR {1: {'name': 'Kitchen'}}
                    val = None
                    if seg_id in rooms_attr:
                        val = rooms_attr[seg_id]
                    elif str(seg_id) in rooms_attr:
                        val = rooms_attr[str(seg_id)]
                    
                    if val:
                        if isinstance(val, dict):
                            vac_room_name = val.get('name') or val.get('custom_name')
                        else:
                            vac_room_name = val
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

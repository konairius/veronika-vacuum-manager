class VeronikaPlanCard extends HTMLElement {
  set hass(hass) {
    if (!this.content) {
      const card = document.createElement('ha-card');
      card.header = 'Cleaning Plan';
      this.content = document.createElement('div');
      this.content.style.padding = '0 16px 16px';
      card.appendChild(this.content);
      this.appendChild(card);
    }

    const entityId = this.config.entity || 'sensor.veronika_cleaning_plan';
    const state = hass.states[entityId];

    if (!state) {
      this.content.innerHTML = 'Entity not found';
      return;
    }

    const plan = state.attributes.plan;
    if (!plan || Object.keys(plan).length === 0) {
      this.content.innerHTML = 'Nothing to clean.';
      return;
    }

    let html = '';
    for (const [vacuum, data] of Object.entries(plan)) {
      // Try to get friendly name for vacuum
      const vacuumState = hass.states[vacuum];
      const vacuumName = vacuumState ? vacuumState.attributes.friendly_name : vacuum;

      html += `<div style="margin-bottom: 10px;">
        <div style="display: flex; align-items: center; margin-bottom: 4px;">
            <ha-icon icon="mdi:robot-vacuum" style="margin-right: 8px;"></ha-icon>
            <strong>${vacuumName}</strong>
            <span style="margin-left: auto; background: var(--primary-color); color: var(--text-primary-color); padding: 2px 6px; border-radius: 4px; font-size: 0.8em;">${data.count}</span>
        </div>
        <div style="background: var(--secondary-background-color); border-radius: 8px; padding: 8px;">
            ${data.rooms.map((room, index) => {
                let icon = 'mdi:circle-outline';
                let color = 'var(--secondary-text-color)';
                let subtext = room.reason;
                
                if (room.will_clean) {
                    icon = 'mdi:check-circle';
                    color = 'var(--success-color, #4caf50)';
                } else if (!room.enabled) {
                    icon = 'mdi:toggle-switch-off-outline';
                    if (room.ready) {
                        subtext = 'Disabled (Ready)';
                        color = 'var(--secondary-text-color)';
                    } else {
                        subtext = `Disabled (${room.sensor_reason})`;
                        color = 'var(--error-color, #f44336)';
                    }
                } else if (!room.ready) {
                    icon = 'mdi:alert-circle';
                    color = 'var(--error-color, #f44336)';
                    subtext = room.sensor_reason;
                }

                return `
                <div style="display: flex; align-items: center; padding: 8px 0; border-bottom: ${index < data.rooms.length - 1 ? '1px solid var(--divider-color)' : 'none'}">
                    <ha-icon icon="${icon}" style="color: ${color}; margin-right: 12px;"></ha-icon>
                    <div style="display: flex; flex-direction: column;">
                        <span>${room.name}</span>
                        <span style="font-size: 0.8em; color: var(--secondary-text-color);">${subtext}</span>
                    </div>
                </div>
            `}).join('')}
        </div>
      </div>`;
    }

    this.content.innerHTML = html;
  }

  setConfig(config) {
    this.config = config;
  }

  getCardSize() {
    return 3;
  }
}

customElements.define('veronika-plan-card', VeronikaPlanCard);

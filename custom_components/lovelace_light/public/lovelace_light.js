const parseLocation = () => {
    const data = {};
    data["ws_url"] = `${window.location.protocol == "http:"? "ws:": "wss:"}//${window.location.host}/api/websocket`;

    const query = new URLSearchParams(window.location.search);
    ["token", "cols", "rows", "class"].forEach((item) => {
        if (query.get(item) !== undefined) data[item] = query.get(item);
    });
    console.log(`parseLocation:`, window.location, data, lovelaceLightDashboard);
    return data;
};

class Connection {
    
    socket = undefined;
    connected = false;
    token = undefined;
    ping = undefined;
    id = 0;
    handler = undefined;
    events = {};

    constructor(handler) {
        console.log(`Connection::constructor:`);
        this.handler = handler;
    }

    start(token, url) {
        console.log(`Connection:start:`, url);
        this.token = token;
        this.open(url, 0);
    }

    open(url, timeout) {
        this.setConnected(false);
        setTimeout(() => {
            console.log(`Connection::constructor: ws URL:`, url);
            this.socket = new WebSocket(url);
            this.socket.addEventListener("open", (event) => {
                console.log(`Connection:open:`, event);
                this.id = 1;
                this.events = {};
                this.setConnected(true);
            });
            this.socket.addEventListener("close", (event) => {
                console.log(`Connection:close:`, event);
                this.setConnected(false);
                if (this.ping) {
                    clearInterval(this.ping);
                    this.ping = undefined;
                }
                this.open(url, 1000 * lovelaceLightConfig["reconnect_after"]);
            });
            this.socket.addEventListener("message", (event) => {
                // console.log(`Connection:message:`, event);
                try {
                    const message = JSON.parse(event.data);
                    this.onMessage(message);
                } catch (e) {
                    console.log(`Connection:message: error:`, e, event);
                }
            });
            this.socket.addEventListener("error", (event) => {
                console.log(`Connection:error:`, event);
            });
        }, timeout);
    }

    send(message, with_id) {
        let result = undefined;
        try {
            if (with_id) {
                result = this.id++;
                message["id"] = result;
            }
            // console.log(`Connection:send:`, message, this.connected, with_id);
            if (this.connected) {
                this.socket.send(JSON.stringify(message));
                return result;
            }
        } catch (e) {
            console.log(`Connection:send: error:`, e, message);
        }
        return undefined;
    }

    sendAction(action, index) {
        console.log(`Connection:sendAction: ${action} / ${index}`);
        this.send({
            "type": "lovelace_light/action",
            "slug": lovelaceLightDashboard.slug,
            "dashboard": lovelaceLightDashboard.id,
            "page": lovelaceLightDashboard.page,
            "index": index,
            "action": action,
        }, true);
    }

    requestDashboard() {
        this.send({
            "type": "lovelace_light/get_dashboard",
            "slug": lovelaceLightDashboard.slug,
            "dashboard": lovelaceLightDashboard.id,
            "page": lovelaceLightDashboard.page,
        }, true);
    }

    requestDashboardUpdate() {
        this.subscribeToEvent({
            "type": "subscribe_events",
            "event_type": "lovelace_updated",
        }, "lovelace_updated");
    }

    onMessage(message) {
        // console.log(`Connection:onMessage:`, message);
        switch (message["type"]) {
            case "auth_required": {
                console.log(`Connection:onMessage:auth_required:`, message);
                this.send({"type": "auth", "access_token": this.token});
                break;
            }
            case "auth_ok": {
                console.log(`Connection:onMessage:auth_ok:`, message);
                this.ping = setInterval(() => {
                    this.send({"type": "ping"}, true);
                }, lovelaceLightConfig["ping_interval"] * 1000);
                this.requestDashboard();
                this.requestDashboardUpdate();
                break;
            }
            case "result": {
                // console.log(`Connection:onMessage:result:`, message);
                const result = message["result"];
                if (message["success"] && result) {
                    this.handler(result["response"], result);
                }
                break;
            }
            case "event": {
                const type = this.events[message["id"]];
                if (type) this.handler(type, message["event"]);
                break;
            }
        }
    }

    setConnected(connected) {
        this.connected = connected;
        console.log(`Connection:setConnected:`, connected);
        document.getElementById("connection").className = connected? "connected": "not_connected";
    }

    subscribeToEvent(message, type) {
        const id = this.send(message, true);
        if (id) this.events[id] = type;
    }

    requestUpdates(dashboard) {
        const keys = {};
        dashboard["items"].forEach((item, index) => {
            const id = item["data"]["entity_id"];
            if (id) keys[id] = id;
        });
        const key_list = [];
        for (const key in keys) key_list.push(key);
        this.subscribeToEvent({
            "type": "subscribe_entities",
            "entity_ids": key_list,
        }, "subscribe_entities");
    }

    reconnect() {
        if (this.connected && this.socket) {
            console.log(`Connection:reconnect: closing socket`);
            this.socket.close();
        }
    }
};

class DashboardItem {

    handler = undefined;

    constructor(handler) {
        this.handler = handler;
    }

    attach(root, data) {
        const div = document.createElement("div");
        div.classList.add("item");
        div.style.gridColumn = `${data["x"] + 1} / ${data["x"] + data["w"] + 1}`;
        div.style.gridRow = `${data["y"] + 1} / ${data["y"] + data["h"] + 1}`;
        root.appendChild(div);
        div.addEventListener("touchstart", () => {
            div.classList.add("touch");
            this.handler("tap");
        });
        div.addEventListener("touchcancel", () => { div.classList.remove("touch") });
        div.addEventListener("touchend", () => { div.classList.remove("touch") });
        return div;
    }

    destroy() {}

    onStateUpdate(data) {}

    capitalize(s) {
        if (s && s.length > 0) return s.substring(0, 1).toUpperCase() + s.substring(1);
        return s;
    }

    adjustSize(v, value) {
        if (v.endsWith("%")) {
            return Math.round(value * parseFloat(v.substring(0, v.length - 1)) / 100);
        }
        return Math.round(parseFloat(v));
    }

};

class DashboardItemTile extends DashboardItem {

    containers = {};

    attach(root, data) {
        const div = super.attach(root, data);
        div.classList.add("tile");
        const data_ = data["data"] || {};
        this.entity_id = data_["entity_id"];
        this.title = data_["title"];
        this.icon = data_["icon"];
        this.vertical = false;
        if (data_["vertical"]) {
            div.classList.add("vertical");
            this.vertical = true;
        }
        const iconCont = document.createElement("div");
        iconCont.classList.add("icon_container");
        const textCont = document.createElement("div");
        textCont.classList.add("text_container");
        div.appendChild(iconCont);
        div.appendChild(textCont);

        const title = document.createElement("div");
        title.classList.add("title");
        // title.innerText = "Title";
        const state = document.createElement("div");
        state.classList.add("state");
        if (data_["hide_state"]) state.style.display = "none";
        // state.innerText = "State";
        textCont.appendChild(title);
        textCont.appendChild(state);

        const icon = document.createElement("img");
        icon.classList.add("icon");
        iconCont.appendChild(icon);
        
        this.containers = { div, title, state, icon, iconCont };

        return div;
    }

    onStateUpdate(data) {
        const state = data[this.entity_id];
        if (state) {
            // console.log(`DashboardItemTile:onStateUpdate:`, state);
            if (state["s"] == "on") {
                this.containers.div.classList.add("on");
            } else {
                this.containers.div.classList.remove("on");
            }
            this.containers.title.innerText = this.title || state["friendly_name"] || "";
            this.containers.state.innerText = `${this.capitalize(state["s"] || "")} ${state["unit_of_measurement"] || ""}`;
            const iconSize = getComputedStyle(this.containers.div).getPropertyValue("--tile-icon-size");
            const size = this.vertical? 
                this.adjustSize(iconSize, this.containers.div.clientWidth): 
                this.adjustSize(iconSize, this.containers.div.clientHeight) 
            ;
            const icon = state["icon"] || this.icon;
            if (icon && icon.startsWith("mdi:")) {
                this.containers.iconCont.style.display = "block";
                const iconColor = getComputedStyle(this.containers.div).getPropertyValue("--tile-icon-color");
                const iconName = icon.substr(4);
                this.containers.icon.src = `/lovelace_light/${lovelaceLightDashboard.slug}/mdi/${iconName}/${iconColor.substring(1)}/${size}.png`;
            } else {
                this.containers.iconCont.style.display = "none";
                // this.containers.icon.src = "";
            }
        }
    }

};

class DashboardItemButton extends DashboardItem {

    containers = {};

    attach(root, data) {
        const div = super.attach(root, data);
        div.classList.add("button");
        const data_ = data["data"] || {};
        this.entity_id = data_["entity_id"];
        this.title = data_["title"];
        this.icon = data_["icon"];
        const iconCont = document.createElement("div");
        iconCont.classList.add("icon_container");
        const textCont = document.createElement("div");
        textCont.classList.add("text_container");
        div.appendChild(iconCont);
        div.appendChild(textCont);

        const title = document.createElement("div");
        title.classList.add("title");
        const state = document.createElement("div");
        state.classList.add("state");
        if (!data_["show_state"]) state.style.display = "none";
        textCont.appendChild(title);
        textCont.appendChild(state);

        const icon = document.createElement("img");
        icon.classList.add("icon");
        iconCont.appendChild(icon);
        
        this.containers = { div, title, state, icon, iconCont };

        return div;
    }

    onStateUpdate(data) {
        const state = data[this.entity_id];
        if (state) {
            // console.log(`DashboardItemTile:onStateUpdate:`, state);
            if (state["s"] == "on") {
                this.containers.div.classList.add("on");
            } else {
                this.containers.div.classList.remove("on");
            }
            this.containers.title.innerText = this.title || state["friendly_name"] || "";
            this.containers.state.innerText = this.capitalize(state["s"] || "");
            const iconSize = getComputedStyle(this.containers.div).getPropertyValue("--button-icon-size");
            const size = this.adjustSize(
                iconSize, 
                Math.min(this.containers.div.clientHeight, this.containers.div.clientWidth),
            );
            const icon = state["icon"] || this.icon;
            if (icon && icon.startsWith("mdi:")) {
                this.containers.iconCont.style.display = "block";
                const iconColor = getComputedStyle(this.containers.div).getPropertyValue("--button-icon-color");
                const iconName = icon.substr(4);
                this.containers.icon.src = `/lovelace_light/${lovelaceLightDashboard.slug}/mdi/${iconName}/${iconColor.substring(1)}/${size}.png`;
            } else {
                this.containers.iconCont.style.display = "none";
            }
        }
    }

};

class DashboardItemPicture extends DashboardItem {

    containers = {};

    attach(root, data) {
        const div = super.attach(root, data);
        div.classList.add("picture");
        const data_ = data["data"] || {};
        this.entity_id = data_["entity_id"];

        const img = document.createElement("img");
        img.classList.add("img");
        div.appendChild(img);
        
        this.containers = { div, img };

        return div;
    }

    onStateUpdate(data) {
        const state = data[this.entity_id];
        if (state) {
            // console.log(`DashboardItemPicture:onStateUpdate:`, state);
            const img = state["entity_picture"] || "";
            this.containers.img.src = `${img}&c=${state["c"]}`;
        }
    }

};

class DashboardItemEntity extends DashboardItem {

    containers = {};

    attach(root, data) {
        const div = super.attach(root, data);
        div.classList.add("entity");
        const data_ = data["data"] || {};
        this.entity_id = data_["entity_id"];
        this.title = data_["title"];
        this.icon = data_["icon"];
        const titleCont = document.createElement("div");
        titleCont.classList.add("title_container");
        const stateCont = document.createElement("div");
        stateCont.classList.add("state_container");
        div.appendChild(titleCont);
        div.appendChild(stateCont);

        const title = document.createElement("div");
        title.classList.add("title");
        const state = document.createElement("div");
        state.classList.add("state");
        const unit = document.createElement("div");
        unit.classList.add("unit");
        titleCont.appendChild(title);
        stateCont.appendChild(state);
        stateCont.appendChild(unit);

        const icon = document.createElement("img");
        icon.classList.add("icon");
        titleCont.appendChild(icon);
        
        this.containers = { div, title, state, unit, icon };

        return div;
    }

    onStateUpdate(data) {
        const state = data[this.entity_id];
        if (state) {
            // console.log(`DashboardItemEntity:onStateUpdate:`, state);
            this.containers.title.innerText = this.title || state["friendly_name"] || "";
            this.containers.unit.innerText = state["unit_of_measurement"] || "";
            this.containers.state.innerText = state["s"] || "";
            const iconSize = getComputedStyle(this.containers.div).getPropertyValue("--entity-icon-size");
            const size = this.adjustSize(
                iconSize, this.containers.div.clientHeight
            );
            const icon = state["icon"] || this.icon;
            if (icon && icon.startsWith("mdi:")) {
                this.containers.icon.style.display = "block";
                const iconColor = getComputedStyle(this.containers.div).getPropertyValue("--entity-icon-color");
                const iconName = icon.substr(4);
                this.containers.icon.src = `/lovelace_light/${lovelaceLightDashboard.slug}/mdi/${iconName}/${iconColor.substring(1)}/${size}.png`;
            } else {
                this.containers.icon.style.display = "none";
            }
        }
    }

};

class Dashboard {
    handler = undefined;
    div = undefined;
    items = [];
    states = {};

    constructor(handler) {
        this.handler = handler;
    }

    attach(div) {
        this.div = div;
    }

    rebuild(dashboard, urlData) {
        this.items.forEach((item) => item.destroy());
        
        this.div.innerHTML = "";
        this.div.className = `dashboard dashboard-${lovelaceLightDashboard.id} page-${lovelaceLightDashboard.page}`
        if (urlData["class"]) {
            this.div.classList.add(urlData["class"]);
        }
        console.log(`Dashboard:rebuild:`, dashboard, this.div.clientWidth, this.div.clientHeight);
        const cols = urlData["cols"] || dashboard["cols"] || 1;
        const rows = urlData["rows"] || dashboard["rows"] || 1;
        this.div.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
        this.div.style.gridTemplateRows = `repeat(${rows}, 1fr)`;

        const createItem = (index, data) => {
            let item = undefined;
            switch (data["data"]["layout"]) {
                case "tile": {
                    item = new DashboardItemTile((action) => {
                        this.handler(`item_${action}`, index, data);
                    });
                    break;
                }
                case "button": {
                    item = new DashboardItemButton((action) => {
                        this.handler(`item_${action}`, index, data);
                    });
                    break;
                }
                case "entity": {
                    item = new DashboardItemEntity((action) => {
                        this.handler(`item_${action}`, index, data);
                    });
                    break;
                }
                case "picture": {
                    item = new DashboardItemPicture((action) => {
                        this.handler(`item_${action}`, index, data);
                    });
                    break;
                }
            }
            if (item) {
                const div = item.attach(this.div, data);
                div.classList.add(`item-${index}`);
                return item;
            }
            return undefined;
        };
        this.items = [];
        this.states = {};
        dashboard["items"].forEach((item, index) => {
            const item_ = createItem(index, item);
            if (item_) this.items.push(item_);
        });
    }

    updateWithState(data) {
        const states = {};
        const extendState = (data, src) => {
            const copy_fields = ["s", "c", "lc", "icon", "friendly_name", "unit_of_measurement", "entity_picture"];
            copy_fields.forEach((field) => {
                if (src && src[field] != undefined) data[field] = src[field];
            });
            return data;
        };
        for (const [key, item] of Object.entries(data["a"] || {})) {
            this.states[key] = extendState(this.states[key] || {}, item);
            this.states[key] = extendState(this.states[key], item["a"]);
            states[key] = this.states[key];
        }
        for (const [key, item] of Object.entries(data["c"] || {})) {
            this.states[key] = extendState(this.states[key] || {}, item);
            if (item["+"]) {
                this.states[key] = extendState(this.states[key], item["+"]);
                this.states[key] = extendState(this.states[key], item["+"]["a"]);
            }
            if (item["-"] && this.states[key]) {
                item["-"]["a"].forEach((field) => {
                    delete this.states[key][field];
                })
            }
            states[key] = this.states[key];
        }
        this.items.forEach((item) => {
            item.onStateUpdate(states);
        });
    }
};

const clickAudio = new Audio("/lovelace_light/media/click1.wav");
const playClick = () => {
    clickAudio.currentTime = 0;
    clickAudio.play();
};

const urlData = parseLocation();

const connection = new Connection((message, data) => {
    console.log(`Connection:handler:`, message, data);
    switch (message) {
        case "lovelace_light/get_dashboard": {
            dashboard.rebuild(data["dashboard"], urlData);
            connection.requestUpdates(data["dashboard"]);
            break;
        }
        case "subscribe_entities": {
            dashboard.updateWithState(data);
            break;
        }
        case "lovelace_updated": {
            if ((data["data"] || {})["url_path"] == lovelaceLightDashboard.id) {
                connection.reconnect();
            }
        }
    }
});

const dashboard = new Dashboard((message, index) => {
    switch (message) {
        case "item_tap": {
            connection.sendAction("tap", index);
            break;
        }
    }
});

document.addEventListener("DOMContentLoaded", () => {
    dashboard.attach(document.getElementById("root"));
    connection.start(urlData["token"], urlData["ws_url"]);
});

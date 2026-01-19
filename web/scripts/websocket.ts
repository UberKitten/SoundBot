/**
 * WebSocket client for real-time sound updates.
 * Connects to the server and listens for sound update events,
 * enabling cache busting without requiring page refresh.
 */

export interface SoundUpdateEvent {
  type: "sound_update";
  sound_name: string;
  modified: string; // ISO datetime string
  action: "add" | "edit" | "delete" | "rename";
}

type SoundUpdateCallback = (event: SoundUpdateEvent) => void;

const callbacks: SoundUpdateCallback[] = [];
let socket: WebSocket | null = null;
let reconnectTimeout: number | null = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000; // 30 seconds max

/**
 * Get the WebSocket URL based on current location.
 */
function getWebSocketUrl(): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws`;
}

/**
 * Calculate reconnect delay with exponential backoff.
 */
function getReconnectDelay(): number {
  const baseDelay = 1000;
  const delay = Math.min(baseDelay * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
  return delay;
}

/**
 * Connect to the WebSocket server.
 */
function connect(): void {
  if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) {
    return;
  }

  const url = getWebSocketUrl();
  console.log("[ws] Connecting to", url);

  try {
    socket = new WebSocket(url);

    socket.onopen = () => {
      console.log("[ws] Connected");
      reconnectAttempts = 0;
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SoundUpdateEvent;
        if (data.type === "sound_update") {
          console.log(`[ws] Sound update: ${data.sound_name} (${data.action})`);
          callbacks.forEach((cb) => {
            try {
              cb(data);
            } catch (e) {
              console.error("[ws] Error in callback:", e);
            }
          });
        }
      } catch (e) {
        console.error("[ws] Error parsing message:", e);
      }
    };

    socket.onclose = (event) => {
      console.log("[ws] Disconnected, code:", event.code);
      socket = null;
      scheduleReconnect();
    };

    socket.onerror = (error) => {
      console.error("[ws] Error:", error);
    };
  } catch (e) {
    console.error("[ws] Failed to connect:", e);
    scheduleReconnect();
  }
}

/**
 * Schedule a reconnection attempt with exponential backoff.
 */
function scheduleReconnect(): void {
  if (reconnectTimeout !== null) {
    return;
  }

  const delay = getReconnectDelay();
  reconnectAttempts++;
  console.log(`[ws] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);

  reconnectTimeout = window.setTimeout(() => {
    reconnectTimeout = null;
    connect();
  }, delay);
}

/**
 * Register a callback to be called when a sound is updated.
 * Returns a function to unregister the callback.
 */
export function onSoundUpdate(callback: SoundUpdateCallback): () => void {
  callbacks.push(callback);

  // Connect if not already connected
  if (!socket) {
    connect();
  }

  return () => {
    const index = callbacks.indexOf(callback);
    if (index !== -1) {
      callbacks.splice(index, 1);
    }
  };
}

/**
 * Check if WebSocket is connected.
 */
export function isConnected(): boolean {
  return socket?.readyState === WebSocket.OPEN;
}

// Auto-connect on module load if we're in a browser
if (typeof window !== "undefined") {
  // Use visibility API to reconnect when tab becomes visible
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !socket) {
      connect();
    }
  });

  // Initial connection
  connect();
}

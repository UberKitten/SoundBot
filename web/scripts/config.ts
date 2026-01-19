export const SOUNDS_API_PATH = "/api/sounds";
export const SOUNDS_PATH = "/sounds";
export const SETTINGS_PATH = "/api/settings";

// Cache for command prefixes
let commandPrefixes: string[] = ["!"];
let prefixesFetched = false;

/**
 * Fetch command prefixes from the server.
 * Called once on page load.
 */
export async function fetchPrefixes(): Promise<void> {
  if (prefixesFetched) return;
  
  try {
    const response = await fetch(`${SETTINGS_PATH}/prefixes`);
    if (response.ok) {
      const data = await response.json();
      if (Array.isArray(data.prefixes) && data.prefixes.length > 0) {
        commandPrefixes = data.prefixes;
      }
    }
  } catch (e) {
    console.warn("Failed to fetch command prefixes, using default:", e);
  }
  prefixesFetched = true;
}

/**
 * Get a random command prefix from the configured list.
 */
export function getRandomPrefix(): string {
  const index = Math.floor(Math.random() * commandPrefixes.length);
  return commandPrefixes[index];
}

/**
 * Get all command prefixes.
 */
export function getPrefixes(): string[] {
  return [...commandPrefixes];
}

// Fetch prefixes on module load
fetchPrefixes();
import { initAdminUi } from "admin-ui";
import { initAuth } from "auth";
import { SoundboardApp } from "soundboard-app";
import { SoundboardButton } from "soundboard-button";

customElements.define("soundboard-app", SoundboardApp);
customElements.define("soundboard-button", SoundboardButton);

// Auth + admin affordances. Both are no-ops / invisible for anonymous users.
initAdminUi();
initAuth();

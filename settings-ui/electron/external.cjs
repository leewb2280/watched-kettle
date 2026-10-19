// Links the renderer may hand to the default browser: the project's GitHub
// repository and pages under it (branding.RELEASE_REPOSITORY), nothing else.
const REPOSITORY_PATH = "/leewb2280/watched-kettle";

function externalLinkAllowed(value) {
  let url;
  try {
    url = new URL(String(value));
  } catch {
    return false;
  }
  return (
    url.protocol === "https:" &&
    url.host === "github.com" &&
    !url.username &&
    !url.password &&
    (url.pathname === REPOSITORY_PATH ||
      url.pathname.startsWith(REPOSITORY_PATH + "/"))
  );
}

module.exports = { REPOSITORY_PATH, externalLinkAllowed };

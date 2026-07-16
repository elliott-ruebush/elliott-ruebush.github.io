const ARCHIVE_MEDIA_DIR = "freerange_elliott Instagram Archive/_media/";

function resolveShortVideoEmbeds(content) {
  const match = content.match(
    /freerange_elliott Instagram Archive\/_media\/([^/\]\s]+)\//
  );
  if (!match) {
    return content;
  }

  const mediaSlug = match[1];
  const prefix = `${ARCHIVE_MEDIA_DIR}${mediaSlug}/`;
  return content.replace(
    /!\[\[(\d{2}\.(?:mp4|mov))\]\]/gi,
    (_, filename) => `![[${prefix}${filename}]]`
  );
}

function vaultMediaPathToWebPath(vaultRelativePath) {
  return encodeURI(`/img/user/${vaultRelativePath}`);
}

function videoHtml(vaultRelativePath) {
  const webPath = vaultMediaPathToWebPath(vaultRelativePath);
  const lower = vaultRelativePath.toLowerCase();
  const mimeType = lower.endsWith(".mov") ? "video/quicktime" : "video/mp4";
  // Blank lines keep markdown-it from wrapping the player in <p>, which breaks layout.
  return `\n\n<video controls playsinline width="100%" preload="metadata" style="display:block;max-width:100%;margin:1em 0;"><source src="${webPath}" type="${mimeType}"></video>\n\n`;
}

function embedVaultVideos(content) {
  const withResolvedPaths = resolveShortVideoEmbeds(content);
  const embedRegex = /!\[\[([^\]]+\.(?:mp4|mov))(?:\|[^\]]*)?\]\]/gi;

  return withResolvedPaths.replace(embedRegex, (_, vaultRelativePath) => {
    return videoHtml(vaultRelativePath.trim());
  });
}

function videoEmbedMarkdownPlugin(md) {
  const wrap = (original, transform) => (src, env) =>
    original(transform(src), env);

  md.render = wrap(md.render.bind(md), embedVaultVideos);
  md.renderInline = wrap(md.renderInline.bind(md), embedVaultVideos);
}

module.exports = {
  ARCHIVE_MEDIA_DIR,
  resolveShortVideoEmbeds,
  embedVaultVideos,
  videoEmbedMarkdownPlugin,
};

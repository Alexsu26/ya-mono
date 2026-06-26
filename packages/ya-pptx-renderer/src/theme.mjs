export function normalizeTheme(template = {}) {
  const theme = template.theme ?? {};
  return {
    templateId: template.id,
    fontFace: theme.fontFace ?? "Aptos",
    titleFontFace: theme.titleFontFace ?? theme.fontFace ?? "Aptos",
    bodyFontFace: theme.bodyFontFace ?? theme.fontFace ?? "Aptos",
    titleColor: theme.titleColor ?? "222222",
    bodyColor: theme.bodyColor ?? "333333",
    accentColor: theme.accentColor ?? "4A5568",
    secondaryAccentColor: theme.secondaryAccentColor ?? theme.accentColor ?? "4A5568",
    backgroundColor: theme.backgroundColor ?? "FFFFFF",
    surfaceColor: theme.surfaceColor ?? theme.backgroundColor ?? "FFFFFF",
    cardColor: theme.cardColor ?? "FFFFFF",
    cardTextColor: theme.cardTextColor ?? theme.bodyColor ?? "333333",
    assetPolicy: template.asset_policy ?? {}
  };
}

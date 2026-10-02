export function OfferImage({url, width, height, alt}) {
  if (!url) return null;
  const stretch = width === '100%';
  return <img
    src={url}
    alt={alt || 'Business logo'}
    width={stretch ? undefined : width}
    height={height}
    referrerPolicy="no-referrer"
    style={{width: stretch ? '100%' : width, height, objectFit: 'cover', display: 'block'}}
  />;
}

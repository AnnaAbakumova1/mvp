import re

with open('vesuvio_menu_page.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Find all images
imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
print(f'Images found: {len(imgs)}')
for img in imgs[:20]:
    print(f'  {img}')

# Check for background images
bg_imgs = re.findall(r'background[^:]*:\s*url\(["\']?([^)"\'\s]+)["\']?\)', html)
print(f'\nBackground images: {len(bg_imgs)}')
for img in bg_imgs[:10]:
    print(f'  {img}')

# Check for data-lazyload or similar
lazy = re.findall(r'data-(?:original|src|lazy|bgset)="([^"]+)"', html)
print(f'\nLazy-loaded images: {len(lazy)}')
for img in lazy[:10]:
    print(f'  {img}')

# Look for any Tilda-specific structures
print('\n=== Tilda record types ===')
rec_types = re.findall(r'data-record-type="(\d+)"', html)
print(f'Record types: {set(rec_types)}')

# Check for any text that might be menu items
print('\n=== Searching for pizza-related text ===')
if 'pizza' in html.lower() or 'пицц' in html.lower():
    print('Found pizza-related text!')
    # Find context
    for match in re.finditer(r'.{50}пицц.{100}', html, re.IGNORECASE | re.DOTALL):
        print(f'  {match.group()[:150]}')
        break

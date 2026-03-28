# Gemini Handoff: Images Page + Image UI

Read GEMINI-HANDOFF.md fully before starting.

The backend now supports image generation via Z-Image API. Images are saved to `data/files/` and served from `/api/files/{filename}`. The `generate_image` tool returns an artifact side_effect. This session adds the Images workspace page and improves image handling across the UI.

---

## Task G-I1: Images Gallery Page

**Priority:** High

Create a new Images page at `/images` that shows all generated and uploaded images in a gallery view.

### Backend API

Images are stored as files in `data/files/`. Use the existing artifacts API:
- `GET /api/artifacts` returns `{artifacts: [{id, filename, content_type, file_size, created_at}]}`
- Filter client-side for image content types (`image/png`, `image/jpeg`, `image/webp`)
- `GET /api/artifacts/{id}/download` serves the file
- `GET /api/files/{filename}` also serves files directly

### Gallery Layout

```
[Header: "Images" + Upload button]

[Grid of image thumbnails - 3 columns on desktop, 2 on mobile]
  Each card:
  - Thumbnail (cover fit, rounded corners)
  - Filename below
  - Date created
  - Click to open full preview

[Empty state: "No images yet. Ask your agent to generate one."]
```

- Use CSS grid: `grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4`
- Thumbnails should lazy-load (`loading="lazy"` on img tags)
- Sort by created_at descending (newest first)
- Clicking a thumbnail opens the artifact preview panel (existing component)

### Image Preview

When clicking a thumbnail:
- Open full-size image in a modal or the artifact preview panel
- Show: full image, filename, date, file size
- Actions: Download, Share (copy link), Delete
- On mobile: full-screen with back button

### Upload

- "Upload" button in the header
- Opens file picker filtered to images (`accept="image/*"`)
- Uses existing upload endpoint: `POST /api/upload` with multipart form
- New images appear in the gallery immediately

### Route Setup

In `App.tsx`, add the route inside the AppLayout:
```tsx
<Route path="/images" element={<ImagesPage />} />
```

### Files
- Create: `dashboard/src/pages/ImagesPage.tsx`
- Modify: `dashboard/src/App.tsx` (add route)

---

## Task G-I2: Sidebar Navigation Update

**Priority:** High

Add Images to the workspace switcher in the sidebar.

### Sidebar Tabs

The workspace switcher currently has: Chat, Notebooks, Boards. Add Images:

```tsx
<button onClick={() => navigate('/images')} className={...} title="Images">
  <ImageIcon className="h-4 w-4" />
</button>
```

Use `ImageIcon` from lucide-react (or `Image` -- check the import name, might conflict with HTML Image).

### Contextual Sidebar Content

When on `/images`, the sidebar should show:
- List of recent images (thumbnails, small, scrollable)
- The active image highlighted
- "+" button creates... nothing (images are created by the agent). Instead, show "Upload" button.

### Files
- Modify: `dashboard/src/layouts/AppLayout.tsx` (sidebar tabs, contextual content)

---

## Task G-I3: Image Thumbnails in Chat

**Priority:** High

When the agent generates an image, it should show as an inline thumbnail in the chat, not just a download card.

### Current Behavior

The `generate_image` tool returns a side_effect with:
```json
{
  "artifact": {
    "filename": "generated_abc12345.png",
    "content_type": "image/png",
    "download_url": "/api/files/generated_abc12345.png",
    "path": "data/files/generated_abc12345.png"
  }
}
```

The ArtifactCard component renders this as a download card.

### New Behavior

For image artifacts (content_type starts with `image/`), render an inline thumbnail instead of a download card:

```tsx
{artifact.content_type?.startsWith('image/') ? (
  <div className="rounded-xl overflow-hidden border border-border/40 max-w-sm cursor-pointer hover:opacity-90 transition-opacity"
       onClick={() => openArtifactPreview(artifact.id)}>
    <img
      src={artifact.download_url}
      alt={artifact.filename}
      className="w-full h-auto"
      loading="lazy"
    />
    <div className="px-3 py-2 text-xs text-muted-foreground flex justify-between">
      <span>{artifact.filename}</span>
      <div className="flex gap-2">
        <button onClick={(e) => { e.stopPropagation(); downloadArtifact(artifact) }}>Download</button>
        <button onClick={(e) => { e.stopPropagation(); shareArtifact(artifact) }}>Share</button>
      </div>
    </div>
  </div>
) : (
  <ArtifactCard ... />  // existing behavior for non-images
)}
```

### Share Button

"Share" copies the image URL to clipboard or uses `navigator.share()` on mobile:

```tsx
async function shareArtifact(artifact) {
  const url = `${window.location.origin}${artifact.download_url}`
  if (navigator.share) {
    await navigator.share({ title: artifact.filename, url })
  } else {
    await navigator.clipboard.writeText(url)
    toast.success('Link copied')
  }
}
```

### Files
- Modify: `dashboard/src/components/ChatPanel.tsx` (inline image rendering)
- Modify: `dashboard/src/components/ArtifactCard.tsx` (add image detection)

---

## Task G-I4: Image in Artifact Preview Panel

**Priority:** Medium

When an image artifact opens in the preview panel, render it properly.

### Current State

The ArtifactPreview component handles HTML, Markdown, CSV, JSON. Add image handling:

```tsx
if (contentType?.startsWith('image/')) {
  return (
    <div className="flex-1 flex items-center justify-center p-4 bg-muted/20">
      <img
        src={downloadUrl}
        alt={filename}
        className="max-w-full max-h-full object-contain rounded-lg shadow-lg"
      />
    </div>
  )
}
```

### Preview Panel Actions for Images

- Download (existing)
- Share (copy link / native share)
- Open in new tab
- Edit with agent ("Make this image wider", "Add text to this image")
  - This button types a message in the chat like "Edit this image: [filename]"

### Files
- Modify: `dashboard/src/components/ArtifactPreview.tsx`

---

## Task G-I5: Mobile Image Experience

**Priority:** Medium

Ensure images work well on mobile:

- Gallery grid: 2 columns on mobile, larger touch targets
- Image preview: full-screen on mobile with pinch-to-zoom
- Chat thumbnails: max-width 100% of chat area, not overflowing
- Share uses native `navigator.share()` on mobile (includes "Save Image" option)
- Upload from camera: add camera option to the upload button on mobile

### Files
- Modify: `dashboard/src/pages/ImagesPage.tsx`
- Modify: `dashboard/src/components/ChatPanel.tsx`

---

## Task G-I6: Contextual Links Update

**Priority:** Low

Add "Images" to the contextual links below the chat input (alongside Journal, Board, Documents, Email):

```
Journal  ·  Board  ·  Images  ·  Documents
```

"Images" navigates to `/images`.

### Files
- Modify: `dashboard/src/components/ChatPanel.tsx`

---

## Verification

1. Build must pass: `npm run build`
2. TypeScript must compile: `npx tsc --noEmit`
3. Ask the agent "generate an image of a sunset over mountains" -- the image should appear inline in chat as a thumbnail
4. Click the thumbnail -- it should open in the artifact preview panel
5. Navigate to /images -- gallery should show all generated images
6. The sidebar should show Images tab and contextual image list
7. On mobile: gallery is 2 columns, images are full-screen on tap, share works
8. Upload an image from the gallery page -- it should appear in the grid

## Conventions (unchanged)

1. **API responses are flat objects**, not wrapped
2. **Use `get/post/patch/del` from `@/lib/api`** for all HTTP calls
3. **Use `toast` from `sonner`** for notifications
4. **Use `lucide-react`** for all icons
5. **Responsive: `lg:` prefix** for desktop-specific styles
6. **TypeScript must compile**: `cd dashboard && npx tsc --noEmit`
7. **Build must succeed**: `cd dashboard && npm run build`

Log progress in the Communication Log at the bottom of GEMINI-HANDOFF.md.

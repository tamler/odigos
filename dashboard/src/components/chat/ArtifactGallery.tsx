import { Music } from 'lucide-react'
import { Artifact, ArtifactCard } from '@/components/ArtifactCard'

const ImageArtifact = ({ artifact, onClick }: { artifact: Artifact; onClick: () => void }) => {
  return (
    <div className="rounded-xl overflow-hidden border border-border/40 max-w-xs cursor-pointer hover:opacity-95 transition-all shadow-sm group/img"
         onClick={onClick}>
      <div className="relative aspect-square bg-muted flex items-center justify-center overflow-hidden">
        <img
          src={`/api/artifacts/${artifact.id}/thumbnail?size=400`}
          alt={artifact.filename}
          className="w-full h-full object-cover"
          loading="lazy"
        />
      </div>
    </div>
  )
}

const AudioArtifact = ({ artifact, onClick }: { artifact: Artifact; onClick: () => void }) => {
  return (
    <div
      className="rounded-xl overflow-hidden border border-border/40 max-w-xs cursor-pointer hover:border-border transition-all shadow-sm"
      onClick={onClick}
    >
      <div className="p-3 space-y-2">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 bg-primary/10 rounded-md flex items-center justify-center shrink-0">
            <Music className="h-4 w-4 text-primary" />
          </div>
          <span className="text-xs font-medium truncate">{artifact.filename}</span>
        </div>
        <audio
          controls
          preload="metadata"
          className="w-full h-8"
          src={`/api/artifacts/${artifact.id}/download`}
          onClick={(e) => e.stopPropagation()}
        >
          Your browser does not support the audio element.
        </audio>
      </div>
    </div>
  )
}

interface ArtifactGalleryProps {
  artifacts: Artifact[]
  onOpenArtifact: (id: string) => void
}

export function ArtifactGallery({ artifacts, onOpenArtifact }: ArtifactGalleryProps) {
  if (artifacts.length === 0) return null

  return (
    <div className="pt-2 mt-4">
      <div className="flex flex-wrap gap-3">
        {artifacts.map(a => (
          a.content_type?.startsWith('image/') ? (
            <ImageArtifact key={a.id} artifact={a} onClick={() => onOpenArtifact(a.id)} />
          ) : a.content_type?.startsWith('audio/') ? (
            <AudioArtifact key={a.id} artifact={a} onClick={() => onOpenArtifact(a.id)} />
          ) : (
            <ArtifactCard key={a.id} artifact={a} />
          )
        ))}
      </div>
    </div>
  )
}

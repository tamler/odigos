import { useEffect, useRef } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Markdown } from 'tiptap-markdown'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'

// CodeMirror imports
import { EditorView, basicSetup } from 'codemirror'
import { EditorState } from '@codemirror/state'
import { markdown } from '@codemirror/lang-markdown'
import { oneDark } from '@codemirror/theme-one-dark'

interface EditorProps {
  content: string
  contentType?: string
  onChange: (newContent: string) => void
  onSave?: () => void
  readOnly?: boolean
}

export function MarkdownEditor({ content, onChange, readOnly = false }: Omit<EditorProps, 'contentType'>) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Markdown,
      Link.configure({ openOnClick: false }),
      Placeholder.configure({ placeholder: 'Start writing...' }),
    ],
    content: content,
    editable: !readOnly,
    onUpdate: ({ editor }) => {
      onChange((editor.storage as any).markdown.getMarkdown())
    },
    editorProps: {
      attributes: {
        class: 'prose prose-sm dark:prose-invert max-w-none focus:outline-none min-h-[200px]',
      },
    },
  })

  // Sync content if it changes externally (e.g. from CodeMirror tab)
  useEffect(() => {
    if (editor && content !== (editor.storage as any).markdown.getMarkdown()) {
      editor.commands.setContent(content)
    }
  }, [content, editor])

  if (!editor) return null

  return <EditorContent editor={editor} className="p-8 max-w-3xl mx-auto h-full" />
}

export function CodeEditor({ content, onChange, onSave, readOnly = false }: EditorProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)

  useEffect(() => {
    if (!editorRef.current) return

    const state = EditorState.create({
      doc: content,
      extensions: [
        basicSetup,
        markdown(), // For now, default to markdown mode for raw editing
        oneDark,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            onChange(update.state.doc.toString())
          }
        }),
        EditorView.theme({
          '&': { height: '100%' },
          '.cm-scroller': { overflow: 'auto' },
        }),
        EditorState.readOnly.of(readOnly),
        // Simple Ctrl+S handler
        EditorView.domEventHandlers({
          keydown(event) {
            if ((event.ctrlKey || event.metaKey) && event.key === 's') {
              event.preventDefault()
              onSave?.()
              return true
            }
            return false
          }
        })
      ],
    })

    const view = new EditorView({
      state,
      parent: editorRef.current,
    })

    viewRef.current = view

    return () => view.destroy()
  }, [])

  // Sync content if it changes externally (e.g. from Tiptap tab)
  useEffect(() => {
    if (viewRef.current && content !== viewRef.current.state.doc.toString()) {
      viewRef.current.dispatch({
        changes: { from: 0, to: viewRef.current.state.doc.length, insert: content }
      })
    }
  }, [content])

  return <div ref={editorRef} className="h-full w-full font-mono text-sm" />
}

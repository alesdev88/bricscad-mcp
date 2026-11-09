;; Drawing and editing. Relies on the helpers in read.lsp.

;; Every edit runs through here: one undo step on success, no change at all on failure.
;; Only marks work. _.UNDO with a count undoes the listener's own _.DELAY instead.
(defun mcp:edit (worker args / result message)
  (command "_.UNDO" "_Mark")
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply worker args))
  (if (vl-catch-all-error-p result)
    (progn
      (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
      (mcp:cancel-command)
      (command "_.UNDO" "_Back")
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)

;; _Back prompts only when no mark is left, and answering No keeps the drawing as it is.
(defun mcp:undo (steps / undone remaining)
  (setq undone 0 remaining steps)
  (while (> remaining 0)
    (command "_.UNDO" "_Back")
    (if (> (getvar "CMDACTIVE") 0)
      (progn
        (command "_N")
        (setq remaining 0)
      )
      (setq undone (1+ undone)
            remaining (1- remaining))
    )
  )
  (mcp:obj (list (cons "undone" undone) (cons "requested" steps)))
)

;; ---- Choosing what to edit ----

(defun mcp:layer-locked-p (name)
  (= (logand (mcp:group 70 (tblsearch "LAYER" name)) 4) 4)
)

;; An erased entity has no data, which is what stops entdel from restoring it.
;; Layer locks are checked here because vla-move ignores them and entdel fails silently.
(defun mcp:edit-target (handle / entity data kind layer)
  (setq entity (vl-catch-all-apply 'handent (list handle)))
  (if (= (type entity) 'ENAME) (setq data (entget entity)))
  (if (null data) (mcp:fail (strcat "No entity has the handle " handle ".")))
  (setq kind (mcp:group 0 data)
        layer (mcp:group 8 data))
  (if (= kind "ATTRIB")
    (mcp:fail (strcat handle " is an attribute. Change attribute values with bricscad_set_attributes."))
  )
  (if (member kind '("VERTEX" "SEQEND"))
    (mcp:fail (strcat handle " is part of another entity. Use that entity's handle."))
  )
  (if (mcp:layer-locked-p layer)
    (mcp:fail (strcat "Layer " layer " is locked. Unlock it with bricscad_set_layer."))
  )
  entity
)

(defun mcp:edit-targets (handles)
  (mapcar 'mcp:edit-target handles)
)

;; ---- Erase ----

(defun mcp:erase-entities-now (handles / targets)
  (setq targets (mcp:edit-targets handles))
  (foreach entity targets
    (if (null (entdel entity)) (mcp:fail "BricsCAD refused to erase an entity."))
  )
  (mcp:obj (list (cons "erased" (length targets))))
)

(defun mcp:erase-entities (handles)
  (mcp:edit 'mcp:erase-entities-now (list handles))
)

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

;; ---- Layers ----

;; entmake would create a missing layer without saying so.
(defun mcp:require-layer (name)
  (if (tblsearch "LAYER" name)
    name
    (mcp:fail (strcat "Layer " name " does not exist. Create it with bricscad_set_layer."))
  )
)

(defun mcp:ensure-linetype (name / loaded)
  (if (not (tblsearch "LTYPE" name))
    (progn
      (setq loaded
        (vl-catch-all-apply 'vla-load (list (vla-get-linetypes (mcp:active-document)) name "iso.lin")))
      (if (vl-catch-all-error-p loaded)
        (mcp:fail (strcat "Linetype " name " is not in this drawing or in iso.lin."))
      )
    )
  )
)

(defun mcp:same-name-p (first second)
  (= (strcase first) (strcase second))
)

(defun mcp:switch-value (switch)
  (if (= switch 1) :vlax-true :vlax-false)
)

(defun mcp:rename-layer (layer name new-name)
  (if (member (strcase name) '("0" "DEFPOINTS"))
    (mcp:fail (strcat "Layer " name " cannot be renamed."))
  )
  (if (and (tblsearch "LAYER" new-name) (not (mcp:same-name-p name new-name)))
    (mcp:fail (strcat "A layer named " new-name " already exists."))
  )
  (vla-put-name layer new-name)
)

(defun mcp:set-layer-now (name new-name color linetype on frozen locked / created layer)
  (setq created (null (tblsearch "LAYER" name))
        layer (vla-add (vla-get-layers (mcp:active-document)) name))
  (if color (vla-put-color layer color))
  (if linetype
    (progn
      (mcp:ensure-linetype linetype)
      (vla-put-linetype layer linetype)
    )
  )
  (if on (vla-put-layeron layer (mcp:switch-value on)))
  (if (and (= frozen 1) (mcp:same-name-p name (getvar "CLAYER")))
    (mcp:fail (strcat "Layer " name " is the current layer and cannot be frozen."))
  )
  (if frozen (vla-put-freeze layer (mcp:switch-value frozen)))
  (if locked (vla-put-lock layer (mcp:switch-value locked)))
  (if new-name (mcp:rename-layer layer name new-name))
  (mcp:obj
    (list
      (cons "layer" (mcp:layer-item (tblsearch "LAYER" (if new-name new-name name))))
      (cons "created" (mcp:bool created))
    )
  )
)

(defun mcp:set-layer (name new-name color linetype on frozen locked)
  (mcp:edit 'mcp:set-layer-now (list name new-name color linetype on frozen locked))
)

;; ---- Modify ----

(defun mcp:set-entity-text (object kind text)
  (if (not (vlax-property-available-p object 'TextString))
    (mcp:fail (strcat kind " has no text."))
  )
  (if (and (= kind "TEXT") (vl-string-search "\\P" text))
    (mcp:fail "TEXT holds one line. Use MTEXT for line breaks.")
  )
  (vla-put-textstring object text)
)

(defun mcp:modify-entities-now (handles move rotate scale layer color linetype text / targets object)
  (setq targets (mcp:edit-targets handles))
  (if layer (mcp:require-layer layer))
  (if linetype (mcp:ensure-linetype linetype))
  (foreach entity targets
    (setq object (vlax-ename->vla-object entity))
    (if layer (vla-put-layer object layer))
    (if color (vla-put-color object color))
    (if linetype (vla-put-linetype object linetype))
    (if text (mcp:set-entity-text object (mcp:group 0 (entget entity)) text))
    (if move (vla-move object (vlax-3d-point '(0.0 0.0 0.0)) (vlax-3d-point move)))
    (if rotate (vla-rotate object (vlax-3d-point (cadr rotate)) (car rotate)))
    (if scale (vla-scaleentity object (vlax-3d-point (cadr scale)) (car scale)))
  )
  (mcp:obj (list (cons "modified" (length targets))))
)

(defun mcp:modify-entities (handles move rotate scale layer color linetype text)
  (mcp:edit 'mcp:modify-entities-now (list handles move rotate scale layer color linetype text))
)

;; ---- Attributes ----

(defun mcp:join (items separator / out)
  (foreach item items
    (setq out (if out (strcat out separator item) item))
  )
  (cond (out) (""))
)

;; pairs is a list of (tag text). Sets every attribute with that tag and returns how many.
(defun mcp:apply-attribute-values (object pairs / attributes count matched)
  (setq attributes (vlax-invoke object 'GetAttributes)
        count 0)
  (foreach pair pairs
    (setq matched nil)
    (foreach attribute attributes
      (if (mcp:same-name-p (vla-get-tagstring attribute) (car pair))
        (progn
          (vla-put-textstring attribute (cadr pair))
          (setq matched T
                count (1+ count))
        )
      )
    )
    (if (not matched)
      (mcp:fail
        (strcat "No attribute " (car pair) " on this insert. It has: "
                (mcp:join (mapcar 'vla-get-tagstring attributes) ", ") "."))
    )
  )
  count
)

(defun mcp:attribute-insert (handle entity / object)
  (if (= (mcp:group 0 (entget entity)) "INSERT") (setq object (vlax-ename->vla-object entity)))
  (if (or (null object) (= (vla-get-hasattributes object) :vlax-false))
    (mcp:fail (strcat handle " is not a block insert with attributes."))
  )
  object
)

(defun mcp:set-attributes-now (updates / targets count)
  (setq targets (mcp:edit-targets (mapcar 'car updates))
        count 0)
  (foreach pair (mapcar 'cons updates targets)
    (setq count
      (+ count
         (mcp:apply-attribute-values
           (mcp:attribute-insert (caar pair) (cdr pair))
           (cadar pair))))
  )
  (mcp:obj (list (cons "inserts" (length updates)) (cons "attributes" count)))
)

(defun mcp:set-attributes (updates)
  (mcp:edit 'mcp:set-attributes-now (list updates))
)

;; ---- Create ----

(defun mcp:layout-name (layout / match)
  (if layout
    (progn
      (foreach name (cons "Model" (layoutlist))
        (if (mcp:same-name-p name layout) (setq match name))
      )
      (cond (match) ((mcp:fail (strcat "Layout " layout " does not exist."))))
    )
    "Model"
  )
)

(defun mcp:space-groups (layout)
  (list (cons 67 (if (= layout "Model") 0 1)) (cons 410 layout))
)

(defun mcp:style-groups (style)
  (if style
    (if (tblsearch "STYLE" style)
      (list (cons 7 style))
      (mcp:fail (strcat "Text style " style " does not exist in this drawing."))
    )
  )
)

(defun mcp:entmake-on (kind subclass layer layout groups / entity)
  (setq entity
    (entmakex
      (append
        (list (cons 0 kind) '(100 . "AcDbEntity"))
        (mcp:space-groups layout)
        (list (cons 8 layer) (cons 100 subclass))
        groups
      )
    )
  )
  (if (null entity) (mcp:fail (strcat "BricsCAD refused to create a " kind ".")))
  entity
)

(defun mcp:make-line (layer layout start end)
  (mcp:entmake-on "LINE" "AcDbLine" layer layout (list (cons 10 start) (cons 11 end)))
)

(defun mcp:polyline-groups (vertices bulges / out index)
  (setq index 0)
  (foreach vertex vertices
    (setq out (cons (cons 10 vertex) out))
    (if bulges (setq out (cons (cons 42 (nth index bulges)) out)))
    (setq index (1+ index))
  )
  (reverse out)
)

(defun mcp:make-polyline (layer layout vertices bulges closed elevation)
  (mcp:entmake-on "LWPOLYLINE" "AcDbPolyline" layer layout
    (append
      (list (cons 90 (length vertices)) (cons 70 (if closed 1 0)) (cons 38 elevation))
      (mcp:polyline-groups vertices bulges)
    )
  )
)

(defun mcp:make-circle (layer layout center radius)
  (mcp:entmake-on "CIRCLE" "AcDbCircle" layer layout (list (cons 10 center) (cons 40 radius)))
)

(defun mcp:make-arc (layer layout center radius start-angle end-angle)
  (mcp:entmake-on "ARC" "AcDbCircle" layer layout
    (list (cons 10 center) (cons 40 radius) '(100 . "AcDbArc") (cons 50 start-angle) (cons 51 end-angle))
  )
)

(defun mcp:make-text (layer layout position text height rotation style)
  (mcp:entmake-on "TEXT" "AcDbText" layer layout
    (append
      (list (cons 10 position) (cons 40 height) (cons 1 text) (cons 50 rotation))
      (mcp:style-groups style)
    )
  )
)

(defun mcp:make-mtext (layer layout position text height width style)
  (mcp:entmake-on "MTEXT" "AcDbMText" layer layout
    (append
      (list (cons 10 position) (cons 40 height) (cons 41 width) (cons 1 text))
      (mcp:style-groups style)
    )
  )
)

;; item is (kind layer arguments...), and kind names the mcp:make- function that draws it.
(defun mcp:make (item layout)
  (apply
    (read (strcat "mcp:make-" (car item)))
    (append (list (mcp:require-layer (cadr item)) layout) (cddr item))
  )
)

(defun mcp:create-entities-now (layout items / name created)
  (setq name (mcp:layout-name layout))
  (setq created (mapcar (function (lambda (item) (mcp:make item name))) items))
  (mcp:obj
    (list
      (cons "created" (mcp:arr (mapcar 'mcp:entity-item created)))
      (cons "count" (length created))
    )
  )
)

(defun mcp:create-entities (layout items)
  (mcp:edit 'mcp:create-entities-now (list layout items))
)

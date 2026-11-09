;; Reading drawings. Results are plain values that json.lsp can encode.

(defun mcp:bool (value)
  (if (or (null value) (= value :vlax-false)) 'mcp:false T)
)

(defun mcp:active-modified-p ()
  (= (vla-get-saved (mcp:active-document)) :vlax-false)
)

(defun mcp:count-selection (selection)
  (if selection (sslength selection) 0)
)

(defun mcp:drawing-info (/ document)
  (setq document (mcp:active-document))
  (mcp:obj
    (list
      (cons "name" (getvar "DWGNAME"))
      (cons "path" (strcat (getvar "DWGPREFIX") (getvar "DWGNAME")))
      (cons "read_only" (mcp:bool (vla-get-readonly document)))
      (cons "modified" (mcp:bool (mcp:active-modified-p)))
      (cons "units" (getvar "INSUNITS"))
      (cons "limits" (list (getvar "LIMMIN") (getvar "LIMMAX")))
      (cons "current_layout" (getvar "CTAB"))
      (cons "extents" (list (getvar "EXTMIN") (getvar "EXTMAX")))
      (cons "entity_count" (mcp:count-selection (ssget "_X")))
      (cons "layouts" (cons "Model" (layoutlist)))
    )
  )
)

(defun mcp:open-drawing (path read-only)
  (vla-open (mcp:documents) path (if read-only :vlax-true :vlax-false))
  (mcp:drawing-info)
)

;; The listener stops if the only document closes, so a blank one takes its place.
;; vla-close never prompts. Unlike _.CLOSE it cannot save by accident.
(defun mcp:close-drawing (/ document)
  (setq document (mcp:active-document))
  (if (= (vla-get-count (mcp:documents)) 1) (vla-add (mcp:documents)))
  (vla-close document :vlax-false)
  (getvar "DWGNAME")
)

;; ---- Shared helpers ----

(defun mcp:fail (message)
  (setq *mcp-pending-error* message)
  (exit)
)

(defun mcp:page (items total limit offset)
  (mcp:obj
    (list
      (cons "items" (mcp:arr items))
      (cons "total" total)
      (cons "limit" limit)
      (cons "offset" offset)
    )
  )
)

(defun mcp:slice (items limit offset / out)
  (repeat offset (setq items (cdr items)))
  (while (and items (> limit 0))
    (setq out (cons (car items) out)
          items (cdr items)
          limit (1- limit))
  )
  (reverse out)
)

(defun mcp:selection-list (selection / index out)
  (if selection
    (progn
      (setq index (sslength selection))
      (while (> index 0)
        (setq index (1- index)
              out (cons (ssname selection index) out))
      )
    )
  )
  out
)

(defun mcp:selection-slice (selection limit offset / index last out)
  (if selection
    (progn
      (setq index offset
            last (min (sslength selection) (+ offset limit)))
      (while (< index last)
        (setq out (cons (ssname selection index) out)
              index (1+ index))
      )
    )
  )
  (reverse out)
)

(defun mcp:select (filter)
  (if filter (ssget "_X" filter) (ssget "_X"))
)

;; Makes a name safe as a selection filter, where # @ . * ? ~ [ ] - , ` are wildcards.
(defun mcp:wild-literal (text / out)
  (foreach code (vl-string->list text)
    (setq out
      (if (member code '(35 64 46 42 63 126 91 93 45 44 96))
        (cons code (cons 96 out))
        (cons code out)
      )
    )
  )
  (vl-list->string (reverse out))
)

(defun mcp:table-records (table / record out)
  (setq record (tblnext table T))
  (while record
    (setq out (cons record out)
          record (tblnext table))
  )
  (reverse out)
)

(defun mcp:group (code data) (cdr (assoc code data)))

(defun mcp:layout-of (data) (cond ((mcp:group 410 data)) ("Model")))

;; ---- Layers and layouts ----

(defun mcp:layer-item (record / name color flags)
  (setq name (mcp:group 2 record)
        color (mcp:group 62 record)
        flags (mcp:group 70 record))
  (mcp:obj
    (list
      (cons "name" name)
      (cons "on" (mcp:bool (>= color 0)))
      (cons "frozen" (mcp:bool (= (logand flags 1) 1)))
      (cons "locked" (mcp:bool (= (logand flags 4) 4)))
      (cons "color" (abs color))
      (cons "linetype" (mcp:group 6 record))
      (cons "entity_count"
            (mcp:count-selection (ssget "_X" (list (cons 8 (mcp:wild-literal name))))))
    )
  )
)

(defun mcp:list-layers (limit offset / records)
  (setq records (mcp:table-records "LAYER"))
  (mcp:page (mapcar 'mcp:layer-item (mcp:slice records limit offset)) (length records) limit offset)
)

(defun mcp:layout-item (name)
  (mcp:obj
    (list
      (cons "name" name)
      (cons "entity_count" (mcp:count-selection (ssget "_X" (list (cons 410 (mcp:wild-literal name))))))
      (cons "is_model" (mcp:bool (= name "Model")))
    )
  )
)

(defun mcp:list-layouts (limit offset / names)
  (setq names (cons "Model" (layoutlist)))
  (mcp:page (mapcar 'mcp:layout-item (mcp:slice names limit offset)) (length names) limit offset)
)

;; ---- Blocks and xrefs ----

(defun mcp:block-records (/ out)
  (foreach record (mcp:table-records "BLOCK")
    (if (not (wcmatch (strcase (mcp:group 2 record)) "`*MODEL_SPACE*,`*PAPER_SPACE*"))
      (setq out (cons record out))
    )
  )
  (reverse out)
)

(defun mcp:block-entities (record / entity out)
  (setq entity (mcp:group -2 record))
  (while entity
    (setq out (cons entity out)
          entity (entnext entity))
  )
  out
)

;; Each state of a dynamic block is an anonymous block, and inserts use that name. Its
;; BLOCK_RECORD names the source block in xdata. Returns (anonymous-name . source-name) pairs.
(defun mcp:dynamic-block-sources (records / out name owner xdata source)
  (foreach record records
    (if (= (logand (mcp:group 70 record) 1) 1)
      (progn
        (setq name (mcp:group 2 record)
              owner (mcp:group 330 (entget (tblobjname "BLOCK" name)))
              xdata (assoc "AcDbBlockRepBTag" (mcp:group -3 (entget owner '("AcDbBlockRepBTag"))))
              source (if xdata (handent (mcp:group 1005 (cdr xdata)))))
        (if source (setq out (cons (cons name (mcp:group 2 (entget source))) out)))
      )
    )
  )
  out
)

;; The name a person knows a block by: a dynamic block's own name, not its anonymous one.
(defun mcp:source-name (name sources)
  (cond ((cdr (assoc name sources))) (name))
)

(defun mcp:add-count (name counts / key found)
  (setq key (strcase name)
        found (assoc key counts))
  (if found
    (subst (cons key (1+ (cdr found))) found counts)
    (cons (cons key 1) counts)
  )
)

;; How often each block is inserted, in a layout or inside other blocks. An insert of an
;; anonymous state counts for that state and for the dynamic block it comes from.
(defun mcp:insert-counts (records / sources counts tally data)
  (setq sources (mcp:dynamic-block-sources records))
  (setq tally
    (function (lambda (name / source)
      (setq counts (mcp:add-count name counts)
            source (cdr (assoc name sources)))
      (if source (setq counts (mcp:add-count source counts)))
    ))
  )
  (foreach entity (mcp:selection-list (ssget "_X" '((0 . "INSERT"))))
    (tally (mcp:group 2 (entget entity)))
  )
  (foreach record records
    (foreach entity (mcp:block-entities record)
      (setq data (entget entity))
      (if (= (mcp:group 0 data) "INSERT") (tally (mcp:group 2 data)))
    )
  )
  counts
)

(defun mcp:insert-count (name counts)
  (cond ((cdr (assoc (strcase name) counts))) (0))
)

;; Inserts of the blocks matching a name pattern, as a list. Dynamic blocks go by their source
;; name, which a selection filter cannot see, so all anonymous inserts are selected and sorted here.
(defun mcp:select-by-block (filter block sources / pattern name out)
  (setq pattern (strcase block))
  (foreach entity (mcp:selection-list (ssget "_X" (append filter (list (cons 2 (strcat block ",`**"))))))
    (setq name (mcp:group 2 (entget entity)))
    (if (or (wcmatch (strcase name) pattern)
            (wcmatch (strcase (mcp:source-name name sources)) pattern))
      (setq out (cons entity out))
    )
  )
  (reverse out)
)

(defun mcp:list-blocks (include-anonymous limit offset / all counts records flags)
  (setq all (mcp:block-records)
        counts (mcp:insert-counts all))
  (foreach record all
    (setq flags (mcp:group 70 record))
    (if (or include-anonymous (= (logand flags 1) 0))
      (setq records (cons record records))
    )
  )
  (setq records (reverse records))
  (mcp:page
    (mapcar
      (function (lambda (record / name flags)
        (setq name (mcp:group 2 record)
              flags (mcp:group 70 record))
        (mcp:obj
          (list
            (cons "name" name)
            (cons "insert_count" (mcp:insert-count name counts))
            (cons "entity_count" (length (mcp:block-entities record)))
            (cons "is_xref" (mcp:bool (/= (logand flags 12) 0)))
            (cons "is_anonymous" (mcp:bool (= (logand flags 1) 1)))
          )
        )))
      (mcp:slice records limit offset))
    (length records) limit offset)
)

(defun mcp:xref-records (/ out)
  (foreach record (mcp:block-records)
    (if (/= (logand (mcp:group 70 record) 12) 0)
      (setq out (cons record out))
    )
  )
  (reverse out)
)

(defun mcp:xref-item (record / path)
  (setq path (mcp:group 1 record))
  (mcp:obj
    (list
      (cons "name" (mcp:group 2 record))
      (cons "path" path)
      (cons "resolved"
            (mcp:bool (and (= (logand (mcp:group 70 record) 32) 32) path (findfile path))))
    )
  )
)

(defun mcp:list-xrefs (limit offset / records)
  (setq records (mcp:xref-records))
  (mcp:page (mapcar 'mcp:xref-item (mcp:slice records limit offset)) (length records) limit offset)
)

;; ---- Entities ----

(defun mcp:entity-filter (types layer block layout / filter)
  (if types (setq filter (cons (cons 0 types) filter)))
  (if (and block (not types)) (setq filter (cons '(0 . "INSERT") filter)))
  (if layer (setq filter (cons (cons 8 layer) filter)))
  (if layout (setq filter (cons (cons 410 layout) filter)))
  (reverse filter)
)

(defun mcp:bounding-box (entity / box)
  (setq box (vl-catch-all-apply 'vle-getboundingbox (list entity)))
  (if (vl-catch-all-error-p box) nil box)
)

(defun mcp:overlaps-p (box window)
  (and box
       (<= (car (car box)) (nth 2 window))
       (>= (car (cadr box)) (nth 0 window))
       (<= (cadr (car box)) (nth 3 window))
       (>= (cadr (cadr box)) (nth 1 window)))
)

(defun mcp:entity-item (entity / data)
  (setq data (entget entity))
  (mcp:obj
    (list
      (cons "handle" (mcp:group 5 data))
      (cons "type" (mcp:group 0 data))
      (cons "layer" (mcp:group 8 data))
      (cons "layout" (mcp:layout-of data))
      (cons "bbox" (mcp:bounding-box entity))
    )
  )
)

(defun mcp:query-entities (types layer block window layout limit offset / filter selection entities found)
  (setq filter (mcp:entity-filter types layer block layout))
  (if (or block window)
    (progn
      (setq entities
        (if block
          (mcp:select-by-block filter block (mcp:dynamic-block-sources (mcp:block-records)))
          (mcp:selection-list (mcp:select filter))
        )
      )
      (foreach entity entities
        (if (or (null window) (mcp:overlaps-p (mcp:bounding-box entity) window))
          (setq found (cons entity found))
        )
      )
      (setq found (reverse found))
      (mcp:page (mapcar 'mcp:entity-item (mcp:slice found limit offset)) (length found) limit offset)
    )
    (progn
      (setq selection (mcp:select filter))
      (mcp:page
        (mapcar 'mcp:entity-item (mcp:selection-slice selection limit offset))
        (mcp:count-selection selection) limit offset)
    )
  )
)

(defun mcp:get-entity (handle / entity data)
  (setq entity (vl-catch-all-apply 'handent (list handle)))
  (if (= (type entity) 'ENAME) (setq data (entget entity)))
  (if (null data) (mcp:fail (strcat "No entity has the handle " handle ".")))
  (mcp:obj
    (list
      (cons "handle" (mcp:group 5 data))
      (cons "type" (mcp:group 0 data))
      (cons "layer" (mcp:group 8 data))
      (cons "dxf" (mapcar (function (lambda (pair) (list (car pair) (cdr pair)))) data))
    )
  )
)

;; ---- Attributes and text ----

(defun mcp:insert-attributes (insert / entity data out)
  (setq entity (entnext insert) data (if entity (entget entity)))
  (while (and data (= (mcp:group 0 data) "ATTRIB"))
    (setq out (cons entity out)
          entity (entnext entity)
          data (if entity (entget entity)))
  )
  (reverse out)
)

(defun mcp:read-attributes (block layout limit offset / sources inserts filter)
  (setq sources (mcp:dynamic-block-sources (mcp:block-records))
        filter (list '(0 . "INSERT") '(66 . 1)))
  (if layout (setq filter (append filter (list (cons 410 layout)))))
  (setq inserts
    (if block
      (mcp:select-by-block filter block sources)
      (mcp:selection-list (ssget "_X" filter))
    )
  )
  (mcp:page
    (mapcar
      (function (lambda (insert / data)
        (setq data (entget insert))
        (mcp:obj
          (list
            (cons "handle" (mcp:group 5 data))
            (cons "block" (mcp:source-name (mcp:group 2 data) sources))
            (cons "layout" (mcp:layout-of data))
            (cons "attributes"
              (mcp:obj
                (mapcar
                  (function (lambda (attribute / values)
                    (setq values (entget attribute))
                    (cons (mcp:group 2 values) (mcp:group 1 values))))
                  (mcp:insert-attributes insert))))
          )
        )))
      (mcp:slice inserts limit offset))
    (length inserts) limit offset)
)

;; MTEXT longer than 250 characters is split across group 3 values before group 1.
(defun mcp:text-of (data / out)
  (foreach pair data
    (if (member (car pair) '(1 3)) (setq out (cons (cdr pair) out)))
  )
  (apply 'strcat (reverse out))
)

(defun mcp:text-matches-p (text query case-sensitive)
  (if case-sensitive
    (vl-string-search query text)
    (vl-string-search (strcase query) (strcase text))
  )
)

;; A MULTILEADER's text is the group 304 before its first leader (group 302). Later 304s are
;; section markers such as LEADER_LINE{, and one with block content has no text at all.
(defun mcp:multileader-text (data / text)
  (while (and data (not text) (/= (caar data) 302))
    (if (= (caar data) 304) (setq text (cdar data)))
    (setq data (cdr data))
  )
  text
)

;; On a MULTILEADER group 10 is the content base, and group 12 is where the text sits.
(defun mcp:text-position (data)
  (mcp:group (if (= (mcp:group 0 data) "MULTILEADER") 12 10) data)
)

(defun mcp:text-item (data layout text extra)
  (mcp:obj
    (append
      (list
        (cons "handle" (mcp:group 5 data))
        (cons "type" (mcp:group 0 data))
        (cons "text" text)
        (cons "layer" (mcp:group 8 data))
        (cons "layout" layout)
        (cons "position" (mcp:text-position data))
      )
      extra
    )
  )
)

;; One item per matching cell. Cells merged into another read as empty, so they do not repeat it.
(defun mcp:table-matches (entity query case-sensitive / table data row column text out)
  (setq table (vlax-ename->vla-object entity)
        data (entget entity)
        row 0)
  (repeat (vla-get-rows table)
    (setq column 0)
    (repeat (vla-get-columns table)
      (setq text (vla-gettext table row column))
      (if (mcp:text-matches-p text query case-sensitive)
        (setq out
          (cons
            (mcp:text-item data (mcp:layout-of data) text (list (cons "row" row) (cons "column" column)))
            out))
      )
      (setq column (1+ column))
    )
    (setq row (1+ row))
  )
  (reverse out)
)

(defun mcp:find-text (query case-sensitive limit offset / found data text layout)
  (foreach entity (mcp:selection-list (ssget "_X" '((0 . "TEXT,MTEXT"))))
    (setq data (entget entity)
          text (mcp:text-of data))
    (if (mcp:text-matches-p text query case-sensitive)
      (setq found (cons (mcp:text-item data (mcp:layout-of data) text nil) found))
    )
  )
  (foreach entity (mcp:selection-list (ssget "_X" '((0 . "MULTILEADER"))))
    (setq data (entget entity)
          text (mcp:multileader-text data))
    (if (and text (mcp:text-matches-p text query case-sensitive))
      (setq found (cons (mcp:text-item data (mcp:layout-of data) text nil) found))
    )
  )
  (foreach entity (mcp:selection-list (ssget "_X" '((0 . "ACAD_TABLE"))))
    (foreach item (mcp:table-matches entity query case-sensitive)
      (setq found (cons item found))
    )
  )
  (foreach insert (mcp:selection-list (ssget "_X" '((0 . "INSERT") (66 . 1))))
    (setq layout (mcp:layout-of (entget insert)))
    (foreach attribute (mcp:insert-attributes insert)
      (setq data (entget attribute)
            text (mcp:group 1 data))
      (if (mcp:text-matches-p text query case-sensitive)
        (setq found (cons (mcp:text-item data layout text nil) found))
      )
    )
  )
  (setq found (reverse found))
  (mcp:page (mcp:slice found limit offset) (length found) limit offset)
)

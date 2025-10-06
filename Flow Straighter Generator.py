# FlowStraightenerAddIn.py
# A Fusion 360 Add-In that creates a circular flow-straightener with a single form dialog.
# UI: SOLID workspace → CREATE panel (falls back to UTILITIES → Add-Ins panel if needed).

import adsk.core, adsk.fusion, adsk.cam, traceback, math

_app = None
_ui = None
_handlers = []    # keep handlers in scope
_cmd_def = None
_btn_control = None

CMD_ID   = 'philip_pounds_flow_straightener'
CMD_NAME = 'Flow Straightener Generator'
CMD_DESC = 'Create a circular flow-straightener with hex-packed holes.'

# ---------------- Geometry helper ----------------
def build_flow_straightener(design, disk_d, ring, n_across, ligament, part_thk):
    um = design.unitsManager

    # Derived geometry
    hole_d = (disk_d - 2.0*ring - (n_across - 1)*ligament) / float(n_across)
    if hole_d <= 0:
        raise ValueError('Inputs produce non-positive hole diameter. Adjust values.')

    hole_r  = hole_d / 2.0
    pitch_x = hole_d + ligament
    pitch_y = math.sqrt(3.0) * 0.5 * pitch_x
    R_center_max = (disk_d * 0.5) - ring - hole_r
    if R_center_max <= 0:
        raise ValueError('Perimeter ring too large for the given disk and hole size.')

    # New component
    root = design.rootComponent
    occ  = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = adsk.fusion.Component.cast(occ.component)
    comp.name = 'Flow Straightener'

    sketches = comp.sketches
    xy = comp.xYConstructionPlane

    # Base disk
    s_base = sketches.add(xy)
    s_base.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(0,0,0), disk_d/2.0)
    base_prof = s_base.profiles.item(0)

    extrudes = comp.features.extrudeFeatures
    base_ext_in = extrudes.createInput(base_prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    base_ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(part_thk))
    base_ext = extrudes.add(base_ext_in)

    # Holes on top face
    top_face = base_ext.endFaces.item(0)
    s_holes = sketches.add(top_face)
    circles = s_holes.sketchCurves.sketchCircles

    max_rows = int(math.floor(R_center_max / pitch_y)) + 1
    made_any = False
    for j in range(-max_rows, max_rows + 1):
        y = j * pitch_y
        x_off = 0.0 if (j % 2 == 0) else 0.5 * pitch_x
        max_cols = int(math.floor((R_center_max + pitch_x) / pitch_x)) + 1
        for i in range(-max_cols, max_cols + 1):
            x = i * pitch_x + x_off
            if (x*x + y*y) <= (R_center_max * R_center_max + 1e-9):
                circles.addByCenterRadius(adsk.core.Point3D.create(x, y, 0), hole_r)
                made_any = True
    if not made_any:
        raise ValueError('No holes fit with the chosen parameters.')

    # Only cut the circular hole regions (area filter)
    hole_profiles = adsk.core.ObjectCollection.create()
    area_threshold = math.pi * (hole_r * 1.2)**2
    for p in s_holes.profiles:
        try:
            props = p.areaProperties(adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy)
            if props and props.area <= area_threshold:
                hole_profiles.add(p)
        except:
            pass
    if hole_profiles.count == 0:
        raise ValueError('No valid hole profiles found to cut.')

    cut_in = extrudes.createInput(hole_profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    thru_all = adsk.fusion.ThroughAllExtentDefinition.create()
    cut_in.setOneSideExtent(thru_all, adsk.fusion.ExtentDirections.NegativeExtentDirection)
    extrudes.add(cut_in)

    return hole_d, pitch_y

# ---------------- Event handlers ----------------
class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs):
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _ui.messageBox('Switch to the DESIGN workspace and try again.')
                return

            inputs = args.firingEvent.sender.commandInputs

            disk_in   = adsk.core.ValueCommandInput.cast(inputs.itemById('disk_d'))
            ring_in   = adsk.core.ValueCommandInput.cast(inputs.itemById('ring'))
            liga_in   = adsk.core.ValueCommandInput.cast(inputs.itemById('ligament'))
            thk_in    = adsk.core.ValueCommandInput.cast(inputs.itemById('part_thk'))
            n_in      = adsk.core.IntegerSpinnerCommandInput.cast(inputs.itemById('n_across'))

            disk_d  = disk_in.value
            ring    = ring_in.value
            ligament= liga_in.value
            part_thk= thk_in.value
            n_across= n_in.value

            hole_d, pitch_y = build_flow_straightener(design, disk_d, ring, n_across, ligament, part_thk)

            # nice summary toast
            um = design.unitsManager
            msg = (f'Hole diameter ≈ {um.formatInternalValue(hole_d, um.defaultLengthUnits)}\n'
                   f'Row pitch (vertical) ≈ {um.formatInternalValue(pitch_y, um.defaultLengthUnits)}')
            _ui.messageBox(msg)

        except Exception as e:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            cmd = args.command
            cmd.isAutoExecute = False
            cmd.okButtonText = 'OK'
            on_execute = CommandExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

            # Inputs (unit-aware value boxes + integer spinner)
            inputs = cmd.commandInputs
            design = adsk.fusion.Design.cast(_app.activeProduct)
            um = design.unitsManager if design else None
            units = um.defaultLengthUnits if um else 'mm'

            inputs.addValueInput('disk_d',   'Disk Diameter',         units, adsk.core.ValueInput.createByString('60 mm'))
            inputs.addValueInput('ring',     'Perimeter Ring',        units, adsk.core.ValueInput.createByString('2.0 mm'))
            inputs.addIntegerSpinnerCommandInput('n_across', 'Holes Across (widest row)', 1, 200, 1, 6)
            inputs.addValueInput('ligament', 'Ligament (between holes)', units, adsk.core.ValueInput.createByString('1.0 mm'))
            inputs.addValueInput('part_thk', 'Part Thickness',        units, adsk.core.ValueInput.createByString('8.0 mm'))

            # Optional: add an image like Spur Gear
            # (provide your own 300x150 png at same folder named "fs_hero.png")
            try:
                img = inputs.addImageCommandInput('hero', ' ', '')
                img.imageFile = _app.activeUserHomeDirectory + '/fs_hero.png'  # silently ignored if missing
                img.isFullWidth = True
            except:
                pass

        except:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

# ---------------- Add-In lifecycle ----------------
def run(context):
    global _app, _ui, _cmd_def, _btn_control
    try:
        _app = adsk.core.Application.get()
        _ui  = _app.userInterface

        # Create the command definition
        _cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if not _cmd_def:
            _cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC)

        on_created = CommandCreatedHandler()
        _cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        # Add button to SOLID → CREATE panel; fallback to UTILITIES → Add-Ins if needed
        target_panel = _ui.allToolbarPanels.itemById('SolidCreatePanel')
        if not target_panel:
            target_panel = _ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        if target_panel:
            _btn_control = target_panel.controls.addCommand(_cmd_def)
            _btn_control.isPromoted = True

    except:
        if _ui:
            _ui.messageBox('Failed to start Add-In:\n{}'.format(traceback.format_exc()))

def stop(context):
    try:
        global _ui, _cmd_def, _btn_control
        if _btn_control:
            _btn_control.deleteMe()
            _btn_control = None
        if _cmd_def:
            _cmd_def.deleteMe()
            _cmd_def = None
    except:
        if _ui:
            _ui.messageBox('Failed to stop Add-In:\n{}'.format(traceback.format_exc()))

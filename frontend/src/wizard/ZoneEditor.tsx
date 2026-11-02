import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import UndoIcon from '@mui/icons-material/Undo';
import AddIcon from '@mui/icons-material/Add';
import Rotate90DegreesCcwIcon from '@mui/icons-material/Rotate90DegreesCcw';
import Rotate90DegreesCwIcon from '@mui/icons-material/Rotate90DegreesCw';

import { CameraPreview } from './CameraPreview';
import { ZoneCanvas } from './ZoneCanvas';
import type { BoundaryDraft, EditorMode } from './ZoneCanvas';
import { newZoneId } from './convert';
import { KIND_LABELS, ROLE_KINDS, ROLE_LABELS } from './eventCatalog';
import { rotateCCW, rotateCW } from '../lib/videoRotation';
import type { Rotation } from '../lib/videoRotation';
import type { BoundarySide, ZoneKind, ZoneRole, WizardPoint, WizardZone } from './wizardTypes';

export interface ZoneEditorProps {
  cameraId: number;
  zones: WizardZone[];
  requiredRoles: ZoneRole[];
  selectedZoneId: string | null;
  zoneErrors: Record<string, string[]>;
  /** Current display/detection rotation; applied to the preview. */
  rotation: Rotation;
  /** Change the rotation (persisted with the configuration when the wizard is saved). */
  onRotate: (rotation: Rotation) => void;
  onChange: (zones: WizardZone[]) => void;
  onSelectZone: (zoneId: string | null) => void;
}

/** The single zone kind the wizard uses for a role (package role uses `package_area`). */
function kindForRole(role: ZoneRole): ZoneKind {
  return ROLE_KINDS[role][0];
}
/**
 * Interactive zone editor: draw/edit polygons and entrance boundaries over the camera preview.
 *
 * Transient drawing state (current mode, in-progress points) lives here; committed geometry is
 * lifted to the wizard via `onChange`, and coordinates are normalised before they leave the
 * canvas.
 */
export function ZoneEditor({
  cameraId,
  zones,
  requiredRoles,
  selectedZoneId,
  zoneErrors,
  rotation,
  onRotate,
  onChange,
  onSelectZone,
}: ZoneEditorProps) {
  const [mode, setMode] = useState<EditorMode>('select');
  const [draftPolygon, setDraftPolygon] = useState<WizardPoint[] | null>(null);
  const [pendingKind, setPendingKind] = useState<ZoneKind | null>(null);
  const [boundaryDraft, setBoundaryDraft] = useState<BoundaryDraft | null>(null);
  const [boundaryZoneId, setBoundaryZoneId] = useState<string | null>(null);
  const [addRole, setAddRole] = useState<ZoneRole>(requiredRoles[0] ?? 'room_zone_id');

  const selectedZone = zones.find((zone) => zone.id === selectedZoneId) ?? null;

  const updateZone = (zoneId: string, patch: Partial<WizardZone>) => {
    onChange(zones.map((zone) => (zone.id === zoneId ? { ...zone, ...patch } : zone)));
  };

  const resetDrawing = () => {
    setMode('select');
    setDraftPolygon(null);
    setPendingKind(null);
    setBoundaryDraft(null);
    setBoundaryZoneId(null);
  };

  const startZone = () => {
    const kind = kindForRole(addRole);
    setPendingKind(kind);
    setDraftPolygon([]);
    setMode('draw-polygon');
    setBoundaryDraft(null);
  };

  const finishZone = () => {
    if (pendingKind === null || draftPolygon === null || draftPolygon.length < 3) return;
    const id = newZoneId(pendingKind, zones);
    const zone: WizardZone = {
      id,
      name: KIND_LABELS[pendingKind],
      kind: pendingKind,
      polygon: draftPolygon,
      boundary:
        pendingKind === 'entrance'
          ? { p1: { x: 0.1, y: 0.5 }, p2: { x: 0.9, y: 0.5 }, inside_side: 'left' }
          : null,
    };
    onChange([...zones, zone]);
    onSelectZone(id);
    resetDrawing();
  };

  const startBoundary = (zoneId: string) => {
    setBoundaryZoneId(zoneId);
    setBoundaryDraft({ p1: { x: 0.1, y: 0.5 }, p2: null });
    setMode('draw-boundary');
  };

  const handleSurfacePointerDown = (point: WizardPoint) => {
    if (mode === 'draw-polygon') {
      setDraftPolygon((current) => [...(current ?? []), point]);
      return;
    }
    if (mode === 'draw-boundary' && boundaryZoneId !== null) {
      setBoundaryDraft((current) => {
        if (current === null || current.p2 !== null) {
          return { p1: point, p2: null };
        }
        const zone = zones.find((item) => item.id === boundaryZoneId);
        if (zone !== undefined) {
          updateZone(boundaryZoneId, {
            boundary: {
              p1: current.p1,
              p2: point,
              inside_side: zone.boundary?.inside_side ?? 'left',
            },
          });
        }
        return null;
      });
      setMode('select');
      setBoundaryZoneId(null);
      return;
    }
    onSelectZone(null);
  };

  const setBoundarySide = (side: BoundarySide) => {
    if (selectedZone === null || selectedZone.boundary === null) return;
    updateZone(selectedZone.id, { boundary: { ...selectedZone.boundary, inside_side: side } });
  };

  const removeZone = (zoneId: string) => {
    onChange(zones.filter((zone) => zone.id !== zoneId));
    if (selectedZoneId === zoneId) onSelectZone(null);
  };

  const addableRoles = requiredRoles.length > 0 ? requiredRoles : (['room_zone_id'] as ZoneRole[]);

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Draw each zone directly over the camera preview. If the camera publishes a sideways picture,
        use the rotate controls to orient it — the preview rotates but coordinates are still saved
        as fractions of the original camera frame (not screen pixels), and the saved rotation is
        also used for detection. People are tracked by the bottom-centre of the box, so place
        boundaries where a person&apos;s feet cross.
      </Alert>

      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="add-zone-role">Zone to add</InputLabel>
          <Select
            labelId="add-zone-role"
            label="Zone to add"
            value={addRole}
            onChange={(event) => setAddRole(event.target.value as ZoneRole)}
            disabled={mode === 'draw-polygon'}
          >
            {addableRoles.map((role) => (
              <MenuItem key={role} value={role}>
                {ROLE_LABELS[role]}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button
          startIcon={<AddIcon />}
          variant="outlined"
          onClick={startZone}
          disabled={mode === 'draw-polygon'}
        >
          Add zone
        </Button>
        {mode === 'draw-polygon' && (
          <>
            <Button
              onClick={finishZone}
              variant="contained"
              disabled={(draftPolygon?.length ?? 0) < 3}
            >
              Finish zone
            </Button>
            <Button
              startIcon={<UndoIcon />}
              onClick={() => setDraftPolygon((current) => (current ?? []).slice(0, -1))}
              disabled={(draftPolygon?.length ?? 0) === 0}
            >
              Undo point
            </Button>
            <Button color="warning" onClick={resetDrawing}>
              Cancel drawing
            </Button>
          </>
        )}
        {mode === 'draw-boundary' && (
          <Button color="warning" onClick={resetDrawing}>
            Cancel boundary
          </Button>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Chip size="small" variant="outlined" label={`View ${rotation}°`} />
        <Tooltip title="Rotate the preview 90° left">
          <span>
            <IconButton
              size="small"
              aria-label="Rotate view left"
              onClick={() => onRotate(rotateCCW(rotation))}
            >
              <Rotate90DegreesCcwIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Rotate the preview 90° right">
          <span>
            <IconButton
              size="small"
              aria-label="Rotate view right"
              onClick={() => onRotate(rotateCW(rotation))}
            >
              <Rotate90DegreesCwIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Button size="small" onClick={() => onRotate(0)} disabled={rotation === 0}>
          Reset view
        </Button>
      </Stack>

      {mode === 'draw-polygon' && (
        <Alert severity="info">
          Tap or click the preview to add points. {draftPolygon?.length ?? 0} point(s) added; at
          least 3 are needed.
        </Alert>
      )}

      <CameraPreview cameraId={cameraId} rotation={rotation}>
        {(size) => (
          <ZoneCanvas
            width={size.width}
            height={size.height}
            rotation={rotation}
            zones={zones}
            selectedZoneId={selectedZoneId}
            draftPolygon={draftPolygon}
            boundaryDraft={boundaryDraft}
            mode={mode}
            onSurfacePointerDown={handleSurfacePointerDown}
            onSelectZone={onSelectZone}
            onVertexPointerDown={() => undefined}
            onVertexPointerMove={(zoneId, index, point) => {
              const zone = zones.find((item) => item.id === zoneId);
              if (zone === undefined) return;
              const polygon = zone.polygon.map((existing, i) => (i === index ? point : existing));
              updateZone(zoneId, { polygon });
            }}
            onVertexPointerUp={() => undefined}
            onBoundaryHandlePointerDown={() => undefined}
            onBoundaryHandlePointerMove={(zoneId, handle, point) => {
              const zone = zones.find((item) => item.id === zoneId);
              if (zone === undefined || zone.boundary === null) return;
              updateZone(zoneId, { boundary: { ...zone.boundary, [handle]: point } });
            }}
            onBoundaryHandlePointerUp={() => undefined}
          />
        )}
      </CameraPreview>

      {selectedZone !== null && (
        <Box>
          <Divider sx={{ mb: 1 }} />
          <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
            <TextField
              size="small"
              label="Zone name"
              value={selectedZone.name}
              onChange={(event) => updateZone(selectedZone.id, { name: event.target.value })}
            />
            <Chip size="small" label={KIND_LABELS[selectedZone.kind]} />
            <Typography variant="body2" color="text.secondary">
              {selectedZone.polygon.length} point(s)
            </Typography>
            {selectedZone.kind === 'entrance' && (
              <>
                <Button size="small" onClick={() => startBoundary(selectedZone.id)}>
                  Redraw boundary
                </Button>
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={selectedZone.boundary?.inside_side ?? 'left'}
                  onChange={(_event, value: BoundarySide | null) => {
                    if (value !== null) setBoundarySide(value);
                  }}
                  aria-label="Interior side of the boundary"
                >
                  <ToggleButton value="left" aria-label="Interior on the left">
                    Interior: left
                  </ToggleButton>
                  <ToggleButton value="right" aria-label="Interior on the right">
                    Interior: right
                  </ToggleButton>
                </ToggleButtonGroup>
              </>
            )}
            <Tooltip title="Delete this zone">
              <IconButton
                color="error"
                aria-label={`Delete zone ${selectedZone.name}`}
                onClick={() => removeZone(selectedZone.id)}
              >
                <DeleteOutlineIcon />
              </IconButton>
            </Tooltip>
          </Stack>
        </Box>
      )}

      <List dense data-testid="zone-list">
        {zones.length === 0 && (
          <ListItem>
            <ListItemText
              primary="No zones yet."
              secondary="Add a zone and draw it on the preview."
            />
          </ListItem>
        )}
        {zones.map((zone) => {
          const errors = zoneErrors[zone.id] ?? [];
          return (
            <ListItem
              key={zone.id}
              onClick={() => onSelectZone(zone.id)}
              sx={{
                cursor: 'pointer',
                borderRadius: 1,
                bgcolor: zone.id === selectedZoneId ? 'action.selected' : 'transparent',
              }}
              secondaryAction={
                <Tooltip title="Delete zone">
                  <IconButton
                    edge="end"
                    aria-label={`Delete zone ${zone.name}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      removeZone(zone.id);
                    }}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              }
            >
              <ListItemText
                primary={`${zone.name} — ${KIND_LABELS[zone.kind]}`}
                secondary={errors.length > 0 ? errors.join(' ') : 'Valid'}
                slotProps={{ secondary: { color: errors.length > 0 ? 'error' : 'text.secondary' } }}
              />
            </ListItem>
          );
        })}
      </List>
    </Stack>
  );
}

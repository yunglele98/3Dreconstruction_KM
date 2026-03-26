# PostGIS Layers for Kensington Market 3D

Connection: `host=localhost port=5432 dbname=kensington user=postgres password=test123`

## Layer List for QGIS

Add these layers in QGIS via Database → PostGIS → New Connection:

### Core Layers
| Schema | Table | Type | SRID | Description |
|--------|-------|------|------|-------------|
| opendata | building_footprints | Polygon | 2952 | 753 building outlines |
| opendata | massing_3d | Polygon | 2952 | 464 3D massing (AVG_HEIGHT) |
| opendata | road_centerlines | MultiLine | 2952 | 162 road centerlines |
| opendata | green_spaces | Polygon | 2952 | Parks/green areas |
| opendata | street_trees | Point | 2952 | 55+ tree locations |
| opendata | pedestrian_network | Line | 2952 | 14 pedestrian paths |
| opendata | land_use | Polygon | 4326 | 20 zoning polygons |
| opendata | hcd_zone_influence | Polygon | 4326 | Heritage district boundary |
| opendata | sidewalks | Line | 2952 | Sidewalk centerlines |
| opendata | addresses | Point | 2952 | 85 address points |
| opendata | cycling_network | Line | 4326 | Bike lanes |

### Building Assessment
| Schema | Table | Type | SRID | Description |
|--------|-------|------|------|-------------|
| public | building_assessment | Point | 4326 | 1,075 buildings (149 columns) |

### Field Survey (SRID 4326)
| Schema | Table | Features | Description |
|--------|-------|----------|-------------|
| public | field_trees | 157 | Surveyed tree locations |
| public | field_poles | 168 | Utility poles |
| public | field_bike_racks | 92 | Bike rack locations |
| public | field_signs | 68 | Street signs |
| public | field_terraces | 21 | Outdoor terraces |
| public | field_parking | 11 | Parking areas |
| public | field_public_art | 6 | Public art installations |
| public | field_parks | 6 | Park features |
| public | field_bus_shelters | 1 | Bus shelter |
| public | field_alleys | 17 | Back alleys |
| public | field_establishments | 7 | Business locations |
| public | field_vacant_buildings | 3 | Vacant buildings |
| public | field_intersections | 1 | Intersection details |
| public | ruelles_spatial | 7 | Back alleys (OSM) |

### Reference
| Schema | Table | Description |
|--------|-------|-------------|
| opendata | study_area | Study area boundary polygon |
| opendata | zoning | Zoning districts |
| opendata | osm_pois | OpenStreetMap POIs |
| opendata | employment | Employment points |

## Origin Point

All Blender coordinates use this origin (SRID 2952):
```
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86
```

To convert PostGIS → Blender local: `local_x = ST_X(geom) - 312672.94`

## QGIS Quick Setup

1. Open QGIS
2. Layer → Add Layer → Add PostGIS Layer
3. Connection: host=localhost, port=5432, db=kensington, user=postgres, pass=test123
4. Add layers listed above
5. Set project CRS to EPSG:2952
6. Style building_assessment by ba_facade_material (categorized)
7. Style massing_3d by AVG_HEIGHT (graduated, 0-30m)

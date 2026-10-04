// Reproducible static projection of the supplied asset, for loading and WebGL failures.
// This does not alter the GLB or invent a replacement mark.
import fs from "node:fs";
import { Box3, Color, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const input = new URL("../src/assets/models/AQUA_V2_Final.glb", import.meta.url);
const output = new URL("../src/assets/models/AQUA_V2_Final_static.svg", import.meta.url);
const bytes = fs.readFileSync(input);
const gltf = await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), "");
const scene = gltf.scenes.find((item) => item.name === "AQUA_V2_STUDIO") ?? gltf.scene;
scene.updateMatrixWorld(true);
const bounds = new Box3().setFromObject(scene, true);
const size = bounds.getSize(new Vector3());
const scale = 500 / size.y;
const width = Math.ceil(size.x * scale + 24);
const height = 524;
const direction = new Vector3(-0.45, 0.7, 1).normalize();
const triangles = [];
scene.traverse((mesh) => {
  if (!mesh.isMesh) return;
  const positions = mesh.geometry.attributes.position;
  const vertexColors = mesh.geometry.attributes.color;
  const index = mesh.geometry.index;
  const count = index ? index.count : positions.count;
  // Includes the exported morph pose and bone transforms, not just raw buffer positions.
  const vertices = Array.from({ length: positions.count }, (_, vertex) =>
    mesh.getVertexPosition(vertex, new Vector3()).applyMatrix4(mesh.matrixWorld)
  );
  for (let offset = 0; offset < count; offset += 3) {
    const indices = [0, 1, 2].map((vertex) => index ? index.getX(offset + vertex) : offset + vertex);
    const points = indices.map((vertex) => vertices[vertex]);
    const materialIndex = mesh.geometry.groups.find((group) => offset >= group.start && offset < group.start + group.count)?.materialIndex ?? 0;
    const material = Array.isArray(mesh.material) ? mesh.material[materialIndex] : mesh.material;
    const normal = new Vector3().subVectors(points[1], points[0]).cross(new Vector3().subVectors(points[2], points[0])).normalize();
    if (normal.z <= 0.015) continue;
    const diffuse = 0.64 + 0.58 * Math.max(0, normal.dot(direction));
    const color = new Color().copy(material.color);
    if (vertexColors) {
      const tint = new Color(0, 0, 0);
      indices.forEach((vertex) => tint.add(new Color().fromBufferAttribute(vertexColors, vertex)));
      color.multiply(tint.multiplyScalar(1 / 3));
    }
    color.multiplyScalar(Math.round(diffuse * 8) / 8);
    if (material.emissive) color.add(new Color().copy(material.emissive).multiplyScalar(material.emissiveIntensity ?? 1));
    const coordinates = points.map((point) => `${((point.x - bounds.min.x) * scale + 12).toFixed(1)} ${((bounds.max.y - point.y) * scale + 12).toFixed(1)}`);
    triangles.push({ depth: points.reduce((sum, point) => sum + point.z, 0) / 3, color: `#${color.getHexString()}`, path: `M${coordinates[0]}L${coordinates[1]}L${coordinates[2]}Z` });
  }
});
triangles.sort((a, b) => a.depth - b.depth);
const paths = [];
let previous;
for (const triangle of triangles) {
  if (previous?.color === triangle.color) previous.path += triangle.path;
  else {
    previous = { color: triangle.color, path: triangle.path };
    paths.push(previous);
  }
}
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="AQUA"><title>Static projection of the supplied AQUA V2 Final logo</title>${paths.map((item) => `<path fill="${item.color}" d="${item.path}"/>`).join("")}</svg>`;
fs.writeFileSync(output, svg);
console.log(`Created ${output.pathname.split("/").at(-1)} from ${triangles.length} visible source triangles (${Buffer.byteLength(svg)} bytes).`);

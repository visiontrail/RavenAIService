const path = require('path')

const projectRoot = path.resolve(__dirname, '..', '..')

const toAbsolute = (target) => (path.isAbsolute(target) ? target : path.resolve(projectRoot, target))

const getDataDir = () => toAbsolute(process.env.RAVEN_DATA_DIR || '../data/raven')

const getUploadsDir = () => toAbsolute(process.env.UPLOAD_DIR || path.join(getDataDir(), 'uploads'))

const getMetadataFilePath = () =>
  toAbsolute(process.env.RAVEN_METADATA_FILE || path.join(getDataDir(), 'package-metadata.json'))

const getVectorStorePath = () =>
  toAbsolute(process.env.RAVEN_VECTOR_STORE_PATH || path.join(getDataDir(), 'vector-store'))

module.exports = {
  getDataDir,
  getUploadsDir,
  getMetadataFilePath,
  getVectorStorePath
}

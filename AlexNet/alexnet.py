import tensorflow as tf
import tensorflow_datasets as tfds
from tensorflow import keras
import pickle, urllib

class Data:
    @staticmethod
    def load() -> (tf.data.Dataset, tf.data.Dataset):
        train_ds, validation_ds = tfds.load(name="imagenet2012", split=['train', 'validation'],
                                            data_dir='/home/gpachitariu/HDD/data')
        
        Data.test_assumptions_of_the_input(train_ds)

        return train_ds, validation_ds
    
    # The ML algorithm has a few assumptions of the input. We test the assumptions on the first example.
    # If the input data doesn't follow the assumptions training, testing & predicting will fail because 
    # the algorithm is "calibrated" the wrong way.
    @staticmethod
    def test_assumptions_of_the_input(train_ds):
        for d in train_ds.take(1):
            image = d['image'].numpy()
            # The image has 3 dimensions (height, width, color_channels). Also color_channels=3
            assert len(image.shape) == 3 and image.shape[2] == 3
            # The range of values for pixels are [0, 255]
            assert image.min() == 0
            assert image.max() == 255

    @staticmethod
    def load_labelid_to_names():
        # Hacky way of getting the class names because I couldn't find them in the tensorflow dataset library.
        # More details here: https://gist.github.com/yrevar/942d3a0ac09ec9e5eb3a
        return pickle.load(urllib.request.urlopen('https://gist.githubusercontent.com/yrevar/6135f1bd8dcf2e0cc683/raw/'+
                                                  'd133d61a09d7e5a3b36b8c111a8dd5c4b5d560ee/imagenet1000_clsid_to_human.pkl') )


class Preprocessing:
    # Resize: In the paper for images they kept the ratio, in mine the images were made square
    BUFFER_SIZE = 1000

    @staticmethod
    def _split_dict(t: tf.Tensor) -> (tf.Tensor, tf.Tensor):
        return t['image'], t['label']

    # TODO is the type of the input tf.Tensor?
    @staticmethod
    def _normalize(image: tf.Tensor, label: tf.Tensor) -> (tf.Tensor, tf.Tensor):
        # Change values range from [0, 255] to [-0.5, 0.5]
        image = (image / 255) - 0.5
        return image, label

    @staticmethod
    # this method is only used to reverse normalisation so we can display the images
    def denormalize(image: tf.Tensor) -> tf.Tensor:
        return (image + 0.5) * 255
        
    @staticmethod
    def _augment(image: tf.Tensor, label: tf.Tensor) -> (tf.Tensor, tf.Tensor):
        # These 4 (rotation, brightness, contrast, flip)
        # are added by me as a helper to get to 70% accuracy, not part of the paper
        # TODO img = tf.keras.preprocessing.image.random_rotation(rg=45, fill_mode='constant', cval=0)
        image = tf.image.random_brightness(image, max_delta=0.1)
        image = tf.image.random_contrast(image, lower=0.9, upper=1.1)
        # crop_size = (tf.random.uniform([1])[0] * 0.25 + 0.75) * Preprocessing.IMG_SIZE
        # zoom in & out. max(zoom_out)=original size
        # image = tf.image.random_crop(image, size = (crop_size, crop_size))
        image = tf.image.resize(image, size=tf.constant((224, 224)))
        image = tf.image.random_flip_left_right(image)

        image = tf.clip_by_value(image, -0.5, 0.5)

        return image, label

    @staticmethod
    def create_generator(ds, for_training, batch_size = 128):
        auto=tf.data.experimental.AUTOTUNE

        ds = ds.map(Preprocessing._split_dict, num_parallel_calls=auto)
        ds = ds.map(Preprocessing._normalize, num_parallel_calls=auto)
        
        ds = ds.shuffle(buffer_size=Preprocessing.BUFFER_SIZE)

        if for_training:
            ds = ds.repeat() # repeat forever
            ds = ds.map(Preprocessing._augment, num_parallel_calls=auto)

        if batch_size > 1:
            ds = ds.batch(batch_size)

        # dataset fetches batches in the background while the model is training.
        ds = ds.prefetch(buffer_size=auto)

        return ds

class Model:

    @staticmethod
    def build():

        # Following the paper: "We initialized the weights in each layer from a zero-mean Gaussian distribution with standard deviation 0.01."
        point_zero_one = tf.compat.v1.keras.initializers.RandomNormal(mean=0.0, stddev=0.01)

        # "We initialized the neuron biases in the second, fourth, and fifth convolutional layers,
        # as well as in the fully-connected hidden layers, with the constant 1. This initialization accelerates
        # the early stages of learning by providing the ReLUs with positive inputs. We initialized the neuron
        # biases in the remaining layers with the constant 0."
        one = tf.compat.v2.constant_initializer(value=0.1) # If I leave this to 1 the losse in the beginning will be huge.
        zero = tf.compat.v2.constant_initializer(value=0)


        model = keras.Sequential([

            # 1st conv. layer
            # Number of weights is ((11×11×3+1)×96) = 34944 where:
            #            11 * 11 = convolution filter size
            #                  3 = number of input layers 
            #                  1 = bias
            #                 96 = number of output layers
            keras.layers.Conv2D(96, (11, 11),  input_shape=(224, 224, 3), strides=4, activation='relu', 
                                bias_initializer=zero,
                                kernel_initializer=point_zero_one),
            keras.layers.MaxPooling2D(pool_size=3, strides=2),

            # 2nd conv. layer
            # Number of weights is ((5×5×96+1)×256) = 614656
            keras.layers.Conv2D(256, (5, 5), activation='relu', bias_initializer=one, kernel_initializer=point_zero_one),
            keras.layers.MaxPooling2D(pool_size=3, strides=2),

            # 3rd conv. layer
            keras.layers.Conv2D(384, (3, 3), activation='relu', bias_initializer=zero, kernel_initializer=point_zero_one),

            # 4th conv. layer
            keras.layers.Conv2D(384, (3, 3), activation='relu', bias_initializer=one, kernel_initializer=point_zero_one),

            # 5th conv. layer
            keras.layers.Conv2D(256, (3, 3), activation='relu', bias_initializer=one, kernel_initializer=point_zero_one),
            keras.layers.Flatten(),
            tf.keras.layers.Dropout(rate=0.5),

            keras.layers.Dense(4096, activation='relu', bias_initializer=zero, kernel_initializer=point_zero_one), 
            tf.keras.layers.Dropout(rate=0.5),

            keras.layers.Dense(4096, activation='relu', bias_initializer=zero, kernel_initializer=point_zero_one),

            # 1000 categories
            keras.layers.Dense(1000, activation='softmax', bias_initializer=zero, kernel_initializer=point_zero_one) 
        ])

        
        # TODO 2. From paper: "We used an equal learning rate for all layers, which we adjusted manually throughout training.
        # The heuristic which we followed was to divide the learning rate by 10 when the validation error
        # rate stopped improving with the current learning rate. The learning rate was initialized at 0.01 and
        # reduced three times prior to termination. We trained the network for roughly 90 cycles through the
        # training set of 1.2 million images, which took five to six days on two NVIDIA GTX 580 3GB GPUs"

        # TODO: What is weight decay? Add weight decay.
        # learning_rate_fn = tf.keras.optimizers.schedules.PolynomialDecay(initial_learning_rate=0.001, decay_steps=1200,
        #                                                                 end_learning_rate=0.0005*0.001, power=1)
        

        model.compile(optimizer=tf.keras.optimizers.SGD(learning_rate=0.001, momentum=0.9),  # learning_rate=learning_rate_fn
                    loss='categorical_crossentropy', 
                    metrics=[ # I don't know why but using 'accuracy' doesn't work
                             #tf.keras.metrics.TopKCategoricalAccuracy(k=1), 
                             #tf.keras.metrics.TopKCategoricalAccuracy(k=3),
                             tf.keras.metrics.TopKCategoricalAccuracy(k=10)
                             ])

        return model

    # TODO test it
    @staticmethod
    def save(model : keras.Sequential, path : str):
        mobilenet_save_path = os.path.join(path, "alexnet/1/")
        tf.saved_model.save(model, mobilenet_save_path)

    # TODO test it
    @staticmethod
    def load(path : str) -> keras.Sequential:
        return tf.saved_model.load(path)


# TODO From paper: "At test time, the network makes a prediction by extracting five 224 × 224 patches
# (the four corner patches and the center patch) as well as their horizontal reflections (hence ten patches in all),
# and averaging the predictions made by the network’s softmax layer on the ten patches

def configure_gpu():
    # from https://www.tensorflow.org/guide/gpu#limiting_gpu_memory_growth
    gpus = tf.config.experimental.list_physical_devices('GPU')
    if gpus:
        try:
            # Currently, memory growth needs to be the same across GPUs
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
                logical_gpus = tf.config.experimental.list_logical_devices('GPU')
                print(len(gpus), "Physical GPUs,", len(logical_gpus), "Logical GPUs")
        except RuntimeError as e:
            # Memory growth must be set before GPUs have been initialized
            print(e)

class Alexnet:

    def __init__(self):
        configure_gpu()

    def load_data(self, sample_fraction=1, only_one = False):
        # http://www.image-net.org/challenges/LSVRC/2012/
        # number_categories = 1000 
        # 1.2 million train images
        # 150 000 validation images
        total_train_data_size = 1.2 * 1000 * 1000 # The alternative of counting this would take ages: len(list(train_data))))
        total_validation_data_size = 150 * 1000

        print("Loading input dataset")
        train_data, validation_data = Data.load()

        self.train_data_size = int(sample_fraction * total_train_data_size)
        self.validation_data_size = int(sample_fraction * total_validation_data_size)

        if only_one: 
            # I use this in testing
            self.train_data_size = 1
            self.validation_data_size = 1

        print(f"A fraction of {sample_fraction} was selected from the total data")
        print(f"Number of examples in the Train dataset is {self.train_data_size} and in the Validation dataset is {self.validation_data_size}")    

        self.train_data = train_data.take(self.train_data_size)
        self.validation_data = validation_data.take(self.validation_data_size)

    def create_generator(self, batch_size = 128):
        print("Creating the generators")
        self.batch_size = batch_size
        self.train_augmented_gen = Preprocessing.create_generator(self.train_data, for_training=True, batch_size = self.batch_size)
        self.validation_gen = Preprocessing.create_generator(self.validation_data, for_training=False)
    
    def build_model(self):
        self.model = Model.build()

    def train(self, dataset_iterations=5):
        print("Starting the training")
        self.history = self.model.fit( x=self.train_augmented_gen,
                            validation_data = self.validation_gen,
                            # An epoch is an iteration over the entire x and y data provided.
                            epochs = dataset_iterations,
                            # Total number of steps (batches of samples) before declaring one epoch finished and starting the next epoch
                            steps_per_epoch = self.train_size / batch_size
                            )

    def predict(self, images):
        return self.model.predict(images)



if __name__ == '__main__':
    network = Alexnet()
    network.load_data(sample_fraction=0.1)
    network.create_generator()
    network.build_model()
    #network.train(dataset_iterations=5)
    print(network.predict(network.train_augmented_sample_gen.take(10)))

# Run log
# 3040/9375 [========>.....................] - ETA: 33:06 - loss: 3 652 687.3218 - top_k_categorical_accuracy: 0.9993Traceback (most recent call last):
# 5971/9375 [==================>...........] - ETA: 17:33 - loss: 3 603 590.7420 - top_k_categorical_accuracy: 0.5951Traceback (most recent call last):